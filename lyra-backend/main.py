"""
LYRA — Main Backend Server v3.0 (Conversational Core Edition)
FastAPI + WebSocket hub for real-time AI desktop assistant.
Authoritative gateway with SQLite persistence, model adapters,
consented personal memories, interruption, and safe tool execution.
"""

import asyncio
import base64
import json
import logging
import os
import sys
import multiprocessing
import tempfile
import time
import uuid
from pathlib import Path
from typing import Optional

import httpx

# Native speech libraries can start multiprocessing helpers. Frozen helpers
# must dispatch before constructing the server instead of launching it again.
if __name__ == '__main__':
    multiprocessing.freeze_support()

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from config import settings
from core.local_access import LocalAccessMiddleware, COOKIE_NAME, websocket_authenticated
from core.errors import safe_error
from core.assistant_service import AssistantService
from core.database import db
from core.model_adapter import model_registry
from core.ai_orchestrator import ai
from core.personality_engine import PersonalityEngine
from core.intent_router import IntentRouter
from voice.tts_engine import TTSEngine
from desktop import control
from core.rag_agent import RAGAgent
from core.session_memory import SessionMemory
from core.tool_registry import build_default_registry
from core.agent_executor import AgentExecutor


# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("LYRA")
# Provider URLs can carry credentials; never emit HTTP request URLs.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# ── App ──────────────────────────────────────────────────────────

app = FastAPI(title="LYRA Backend", version="3.0.0")

app.add_middleware(LocalAccessMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.ALLOWED_ORIGINS),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/session")
async def local_browser_session():
    response = JSONResponse({"authenticated": True})
    response.set_cookie(COOKIE_NAME, settings.BACKEND_AUTH_TOKEN, httponly=True, samesite="strict", max_age=43200)
    return response

# Engines
rag_agent = RAGAgent(ai)
tts = TTSEngine()
session_tracker = SessionMemory()
tool_registry = build_default_registry()
agent_executor = AgentExecutor(tool_registry)
assistant_service = AssistantService(db, ai, agent_executor)
app.include_router(assistant_service.router)

# WebSocket connection & session management
ws_clients: dict[str, WebSocket] = {}
ws_sessions: dict[str, dict] = {}  # client_id -> {user_id, conversation_id, active_task}

# Apply saved preferences
if session_tracker.user_name:
    PersonalityEngine.set_user_name(session_tracker.user_name)
PersonalityEngine.set_mode(session_tracker.personality_mode)
session_tracker.increment_session()
logger.info(f"📚 Session #{session_tracker.session_count} | User: {session_tracker.user_name or 'Unknown'}")


# ── REST Endpoints: System & Health ──────────────────────────────

@app.get("/health")
@app.get("/api/health")
async def health():
    return {
        "status": "online",
        "system": "LYRA",
        "instance_id": os.getenv("BACKEND_INSTANCE_ID", ""),
        "version": "3.0.0",
        "timestamp": time.time(),
        "database": "sqlite_wal",
        "provider_status_basis": "Configuration only; credentials and model availability are verified when a task runs.",
        "providers": {
            "anthropic": bool(settings.ANTHROPIC_API_KEY),
            "claude_code": bool(os.path.exists(settings.CLAUDE_BINARY_PATH or "/Users/anilgowtham/.local/bin/claude")),
            "groq": bool(settings.GROQ_API_KEY),
            "gemini": bool(settings.GEMINI_API_KEY),
            "openai": bool(settings.OPENAI_API_KEY),
            "nvidia": bool(settings.NVIDIA_API_KEY),
            "openrouter": bool(settings.OPENROUTER_API_KEY),
            "ollama": bool(settings.OLLAMA_BASE_URL),
        },
        "voice": tts.voice,
    }


@app.get("/api/system/stats")
async def system_stats():
    return await control.get_system_stats()


@app.get("/api/tts")
async def tts_endpoint(text: str):
    """Generate TTS audio and return as base64."""
    result = await tts.speak(text)
    return result


@app.post('/api/tts')
async def tts_body_endpoint(request: dict):
    """Speech text belongs in the body, not in HTTP access-log URLs."""
    text = request.get('text')
    if not isinstance(text, str) or not text.strip() or len(text) > 5000:
        raise ValueError('Speech text must contain between 1 and 5000 characters')
    return await tts.speak(text)


@app.get("/api/voices")
async def list_voices():
    """List available macOS TTS voices."""
    return {"voices": tts.get_available_voices(), "current": tts.voice}


@app.post("/api/voice/set")
async def set_voice(request: dict):
    """Change TTS voice."""
    voice = request.get("voice", "Samantha")
    tts.set_voice(voice)
    return {"voice": tts.voice}


@app.get("/api/apps")
async def list_apps():
    """List available apps."""
    return {"apps": list(control.APP_MAP.keys())}


@app.get("/api/greeting")
async def get_greeting():
    """Get a dynamic personality greeting."""
    greeting = PersonalityEngine.generate_greeting()
    audio = await tts.speak(greeting)
    return {"text": greeting, "audio": audio.get("audio"), "format": audio.get("format")}


# ── REST Endpoints: Conversations & Messages ─────────────────────

@app.get("/api/conversations")
async def list_conversations(user_id: str = "default_user", limit: int = 50):
    """Retrieve all conversations for a user."""
    return {"conversations": db.list_conversations(user_id=user_id, limit=limit)}


@app.post("/api/conversations")
async def create_conversation(request: dict):
    """Create or fetch a conversation."""
    user_id = request.get("user_id", "default_user")
    if "record" in request:
        return db.import_conversation(request["record"], user_id=user_id)
    title = request.get("title", "New Conversation")
    conv_id = request.get("conversation_id")
    conv = db.get_or_create_conversation(conv_id, user_id=user_id, title=title)
    return conv


@app.get("/api/conversations/{conv_id}/messages")
async def get_conversation_messages(conv_id: str, limit: int = 100):
    """Retrieve all multi-turn messages for a conversation."""
    return {"messages": db.get_messages(conv_id, limit=limit)}


@app.delete("/api/conversations/{conv_id}")
async def delete_conversation(conv_id: str):
    """Delete a conversation and its messages."""
    success = db.delete_conversation(conv_id)
    return {"success": success}


# ── REST Endpoints: Consented Personal Memories ─────────────────

@app.get("/api/memories")
async def list_memories(user_id: str = "default_user"):
    """List all personal memories and preferences for a user."""
    return {"memories": db.list_all_memories(user_id=user_id)}


@app.post("/api/memories")
async def add_memory(request: dict):
    """Add a consented personal memory."""
    user_id = request.get("user_id", "default_user")
    fact = request.get("fact", "").strip()
    category = request.get("category", "preference")
    consented = request.get("consented", True)
    if not fact:
        return JSONResponse({"error": "Memory fact cannot be empty"}, status_code=400)
    
    mem = db.add_memory(user_id=user_id, fact=fact, category=category, consented=consented)
    return mem


@app.put("/api/memories/{memory_id}")
async def update_memory(memory_id: str, request: dict):
    """Update or toggle consent/active state of a memory."""
    fact = request.get("fact")
    consented = request.get("consented")
    is_active = request.get("is_active")
    success = db.update_memory(memory_id, fact=fact, consented=consented, is_active=is_active)
    return {"success": success}


@app.delete("/api/memories/{memory_id}")
async def delete_memory(memory_id: str):
    """Forget a specific memory."""
    success = db.delete_memory(memory_id)
    return {"success": success}


@app.delete("/api/memories")
async def clear_memories(user_id: str = "default_user"):
    """Forget all memories for a user."""
    count = db.clear_user_memories(user_id)
    return {"deleted_count": count}


# ── REST Endpoints: Action Audit Log ─────────────────────────────

@app.get("/api/audit-log")
async def get_audit_log(limit: int = 50):
    """Retrieve safe execution audit logs."""
    return {"logs": db.get_audit_log(limit=limit)}


# ── REST Endpoints: Chat & Completions (Authoritative) ────────────

@app.post("/api/chat")
async def chat_endpoint(request: dict):
    """Authoritative chat endpoint supporting full multi-turn context."""
    message = request.get("message", "")
    conversation_id = request.get("conversation_id")
    user_id = request.get("user_id", "default_user")
    model = request.get("model", "")
    temperature = request.get("temperature", 0.6)
    max_tokens = request.get("max_tokens", 600)
    provider = request.get("provider", "")
    is_voice = request.get("is_voice", False)

    if not message:
        return JSONResponse({"error": "Message is required"}, status_code=400)

    result = await ai.chat(
        message=message,
        conversation_id=conversation_id,
        user_id=user_id,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        provider=provider,
        is_voice=is_voice,
    )
    return result


@app.post("/api/chat/stream")
async def chat_stream_endpoint(request: dict):
    """Token-by-token streaming chat endpoint with SSE."""
    message = request.get("message", "")
    conversation_id = request.get("conversation_id")
    user_id = request.get("user_id", "default_user")
    model = request.get("model", "")
    temperature = request.get("temperature", 0.6)
    max_tokens = request.get("max_tokens", 600)
    provider = request.get("provider", "")
    is_voice = request.get("is_voice", False)

    if not message:
        return JSONResponse({"error": "Message is required"}, status_code=400)

    async def stream_gen():
        async for token in ai.stream_chat(
            message=message,
            conversation_id=conversation_id,
            user_id=user_id,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            provider=provider,
            is_voice=is_voice,
        ):
            yield f"data: {json.dumps({'token': token})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(stream_gen(), media_type="text/event-stream")


@app.post("/api/chat/interrupt")
async def interrupt_endpoint():
    """Halt active speech output and interrupt ongoing operations."""
    tts.stop()
    return {"status": "interrupted", "timestamp": time.time()}




@app.post("/v1/chat/completions")
async def openai_compat_chat(request: dict, raw_req: Request):
    """
    OpenAI-compatible chat/completions endpoint.
    Passes full multi-turn conversation messages rather than only the final turn.
    Honors model, temperature, max_tokens, and streaming.
    """
    messages = request.get("messages", [])
    model = request.get("model", "llama-3.3-70b-versatile")
    stream = request.get("stream", False)
    max_tokens = request.get("max_tokens", 1024)
    temperature = request.get("temperature", 0.7)
    conversation_id = request.get("conversation_id") or raw_req.headers.get("x-conversation-id")
    user_id = request.get("user_id", "default_user")

    if not messages:
        return JSONResponse({"error": "No messages provided"}, status_code=400)

    # Extract the latest user message
    last_user_message = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            last_user_message = msg.get("content", "")
            break

    if not last_user_message:
        return JSONResponse({"error": "No user message found in conversation"}, status_code=400)

    # Ensure conversation exists
    conv = db.get_or_create_conversation(conversation_id, user_id=user_id)
    conv_id = conv["id"]

    if stream:
        async def stream_gen():
            async for token in ai.stream_chat(
                message=last_user_message,
                conversation_id=conv_id,
                user_id=user_id,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            ):
                chunk = {
                    "id": f"chatcmpl-{int(time.time())}",
                    "object": "chat.completion.chunk",
                    "model": model,
                    "choices": [{"index": 0, "delta": {"content": token}, "finish_reason": None}],
                }
                yield f"data: {json.dumps(chunk)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(stream_gen(), media_type="text/event-stream")

    # Non-streaming
    result = await ai.chat(
        message=last_user_message,
        conversation_id=conv_id,
        user_id=user_id,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return {
        "id": f"chatcmpl-{int(time.time())}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": result.get("model", model),
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": result.get("response", "")},
            "finish_reason": "stop",
        }],
        "conversation_id": conv_id,
    }


# ── REST Endpoints: STT & Grounding ──────────────────────────────

from voice.transcription import TranscriptionError, TranscriptionService

transcription_service = TranscriptionService()


@app.get("/api/stt/status")
async def speech_to_text_status():
    """Report configured speech models without claiming their keys are valid."""
    try:
        return transcription_service.capabilities()
    except TranscriptionError as error:
        return JSONResponse(error.as_dict(), status_code=error.status_code)


@app.post("/api/stt")
async def speech_to_text(request: dict):
    """Transcribe recorded audio, or explain the actual input/provider failure."""
    try:
        return await transcription_service.transcribe(
            request.get("audio"), request.get("format", "webm"), request.get("language", "en"),
        )
    except TranscriptionError as error:
        logger.warning("Speech transcription failed: %s", error.code)
        return JSONResponse(error.as_dict(), status_code=error.status_code)


# ── Native Speech Execution Endpoints ─────────────────────────────

@app.post("/api/voice/speak")
async def api_voice_speak(request: dict):
    """Speak text directly through Mac speakers via native macOS speech engine."""
    text = request.get("text", "").strip()
    if not text:
        return JSONResponse({"error": "Text is required"}, status_code=400)
    voice = request.get("voice", tts.voice)
    rate = request.get("rate", tts.rate)
    try:
        await tts.speak_direct(text, voice=voice, rate=rate)
        return {"success": True, "text": text}
    except Exception as e:
        logger.error(f"Native speech failed: {safe_error(e)}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/voice/stop")
async def api_voice_stop():
    """Halt any ongoing macOS speech immediately."""
    tts.stop()
    return {"success": True}


# ── AI Voice Terminal Endpoints ───────────────────────────────────

@app.post("/api/terminal/translate")
async def terminal_translate(request: dict):
    """Translate natural language spoken voice intent into a precise macOS zsh command."""
    prompt = request.get("prompt", "").strip()
    cwd = request.get("cwd", str(Path.home() / "Desktop"))

    if not prompt:
        return JSONResponse({"error": "Prompt is required"}, status_code=400)

    # 1. Direct command pass-through check
    lower = prompt.lower().strip()
    direct_prefixes = ("ls", "git", "pwd", "cd", "cat", "echo", "mkdir", "rm", "cp", "mv",
                       "touch", "grep", "find", "curl", "ping", "ps", "top", "df", "du",
                       "uname", "whoami", "npm", "node", "python", "python3", "pip", "brew")
    first_word = lower.split()[0] if lower else ""
    if first_word in direct_prefixes or prompt.startswith("$"):
        cmd = prompt.lstrip("$ ").strip()
        return {"command": cmd, "explanation": f"Executing direct shell command: {cmd}"}

    # 2. Heuristic shortcut matching for lightning-fast voice execution
    heuristics = {
        "list files": "ls -la",
        "show files": "ls -la",
        "check git status": "git status",
        "git status": "git status",
        "git log": "git log -n 5 --oneline",
        "recent commits": "git log -n 5 --oneline",
        "current directory": "pwd",
        "where am i": "pwd",
        "disk usage": "df -h",
        "disk space": "df -h",
        "memory usage": "top -l 1 | head -n 12",
        "cpu usage": "top -l 1 | head -n 12",
        "system info": "uname -a && uptime",
        "battery": "pmset -g batt",
        "battery status": "pmset -g batt",
        "show ip": "ifconfig | grep 'inet ' | grep -v 127.0.0.1",
        "network status": "netstat -rn | head -n 15",
        "running processes": "ps aux | head -n 15",
        "who am i": "whoami",
    }
    for phrase, cmd in heuristics.items():
        if phrase in lower:
            return {"command": cmd, "explanation": f"Voice intent recognized: {cmd}"}

    # 3. LLM Translation via Google Gemini
    if settings.GEMINI_API_KEY:
        try:
            payload = {
                "contents": [{
                    "parts": [{
                        "text": (
                            f"Translate this user voice request into an exact, safe macOS zsh terminal command.\n"
                            f"Working Directory: {cwd}\n"
                            f"Request: \"{prompt}\"\n\n"
                            f"RULES:\n"
                            f"- Return ONLY the command on a single line with no markdown, backticks, or explanation.\n"
                            f"- Ensure it is safe and appropriate for macOS.\n"
                            f"- If not possible to determine, return 'echo \"Command not recognized\"'"
                        )
                    }]
                }],
                "generationConfig": {"temperature": 0.0, "maxOutputTokens": 100}
            }
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={settings.GEMINI_API_KEY}",
                    json=payload
                )
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        cmd = "".join(p.get("text", "") for p in parts).strip()
                        cmd = cmd.strip("` \n\r").lstrip("$ ")
                        return {"command": cmd, "explanation": f"AI translated intent into: {cmd}"}
        except Exception as e:
            logger.warning(f"Gemini terminal translation error: {safe_error(e)}")

    raise HTTPException(status_code=503, detail="No model could translate this request. No command was executed.")


@app.post("/api/terminal/exec")
async def terminal_execute(request: dict):
    return assistant_service.create_task({"tool": "execute_command", "arguments": {
        "command": request.get("command", ""), "cwd": request.get("cwd") or str(Path.home() / "Desktop")},
        "prompt": request.get("command") or "Terminal command"})


@app.post("/api/agent/claude-code")
async def claude_code_execute(request: dict):
    if request.get("dangerously_skip_permissions"):
        raise ValueError("Permission bypass is not allowed")
    return assistant_service.create_task({"tool": "run_claude_code", "arguments": {
        "prompt": request.get("prompt", ""), "cwd": request.get("cwd") or str(Path(__file__).resolve().parent.parent)},
        "prompt": request.get("prompt") or "Coding task"})


@app.post("/api/rag")
async def rag_search(request: dict):
    """RAG search across web, local files, and git."""
    query = request.get("query", "")
    sources = request.get("sources", ["local", "git"])
    base_path = request.get("base_path")
    result = await rag_agent.query(query, sources, base_path)
    return result


@app.post("/api/search")
async def api_search(request: dict):
    """Web search endpoint."""
    from tools.web_search import web_search
    query = request.get("query", "")
    if not query:
        return JSONResponse({"error": "Query is required"}, status_code=400)
    result = await web_search(query=query)
    return {"answer": result.get("result", ""), "success": result.get("success", False)}


# ── Durable task WebSocket bridge ──────────────────────────────────

@app.on_event("startup")
async def start_assistant_services():
    assistant_service.runtime._closed = False
    await assistant_service.reminders.start()


@app.on_event("shutdown")
async def stop_assistant_services():
    await assistant_service.reminders.stop()
    await assistant_service.runtime.shutdown()


@app.exception_handler(ValueError)
async def invalid_input(request: Request, error: ValueError):
    return JSONResponse({"error": safe_error(error)}, status_code=400)


@app.exception_handler(PermissionError)
async def denied_input(request: Request, error: PermissionError):
    return JSONResponse({"error": safe_error(error)}, status_code=403)


@app.websocket("/ws")
async def websocket_hub(websocket: WebSocket):
    if not websocket_authenticated(websocket):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    conv_id = websocket.query_params.get("conversation_id")
    conv = db.get_or_create_conversation(conv_id, user_id="default_user", title="Lyra conversation")
    if conv['user_id'] != 'default_user':
        await websocket.close(code=1008)
        return
    conv_id = conv['id']
    active_id = None
    await websocket.send_json({"type": "greeting", "text": "Connected to the local assistant service.", "conversation_id": conv_id})
    try:
        while True:
            data = await websocket.receive_json()
            kind = data.get('type', 'command')
            if kind == 'ping':
                await websocket.send_json({'type': 'pong', 'timestamp': time.time()})
            elif kind in ('interrupt', 'stop_speaking'):
                if active_id:
                    await assistant_service.runtime.cancel(active_id, user_id='default_user')
                tts.stop()
                await websocket.send_json({'type': 'interrupted'})
                await websocket.send_json({'type': 'state', 'state': 'ready'})
            elif kind == 'set_conversation':
                requested = data.get('content')
                owned = db.get_or_create_conversation(requested, user_id='default_user')
                if owned['user_id'] != 'default_user':
                    raise PermissionError('Conversation belongs to another user')
                conv_id = owned['id']
                await websocket.send_json({'type': 'conversation_set', 'conversation_id': conv_id})
            elif kind == 'tool_approval':
                task_id = data.get('task_id') or active_id
                success = await assistant_service.runtime.approve(task_id, data.get('request_id', ''), data.get('approved') is True, user_id='default_user')
                await websocket.send_json({'type': 'approval_resolved', 'success': success, 'task_id': task_id})
            elif kind in ('command', 'voice_command', 'agent_command', 'rag_query'):
                if active_id and assistant_service.runtime.get(active_id)['status'] in ('running', 'awaiting_approval', 'queued'):
                    await websocket.send_json({'type': 'error', 'message': 'The current task is still active. Stop it before starting another.'})
                    continue
                prompt = data.get('content') or data.get('message') or ''
                metadata = dict(data.get('metadata') or {})
                metadata['is_voice'] = kind == 'voice_command'
                task = assistant_service.create_task({'prompt': prompt, 'conversation_id': data.get('conversation_id') or conv_id,
                    'model': data.get('model', ''), 'provider': data.get('provider', ''), 'metadata': metadata})
                active_id = task['id']
                conv_id = task['conversation_id']
                assistant_service.sockets[active_id] = websocket
                await websocket.send_json({'type': 'task_created', 'task': task, 'task_id': active_id, 'conversation_id': conv_id})
                await websocket.send_json({'type': 'state', 'state': 'thinking'})
            elif kind == 'set_voice':
                tts.set_voice(data.get('voice', 'Samantha'))
                await websocket.send_json({'type': 'voice_changed', 'voice': tts.voice})
            elif kind == 'set_personality':
                PersonalityEngine.set_mode(data.get('mode', 'balanced'))
                await websocket.send_json({'type': 'personality_changed', 'mode': data.get('mode', 'balanced')})
    except WebSocketDisconnect:
        pass
    except Exception as error:
        await websocket.send_json({'type': 'error', 'message': safe_error(error)})
    finally:
        # Work belongs to a durable task and survives a window disconnect.
        for task_id, socket in list(assistant_service.sockets.items()):
            if socket is websocket:
                assistant_service.sockets.pop(task_id, None)


# ── Run ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    logger.info("🚀 LYRA Backend v3.0 starting...")
    logger.info(f"   Groq:       {'✅' if settings.GROQ_API_KEY else '❌'}")
    logger.info(f"   Gemini:     {'✅' if settings.GEMINI_API_KEY else '❌'}")
    logger.info(f"   OpenAI:     {'✅' if settings.OPENAI_API_KEY else '❌'}")
    logger.info(f"   NVIDIA:     {'✅' if settings.NVIDIA_API_KEY else '❌'}")
    logger.info(f"   OpenRouter: {'✅' if settings.OPENROUTER_API_KEY else '❌'}")
    logger.info(f"   Ollama:     {'✅' if settings.OLLAMA_BASE_URL else '❌'}")
    logger.info(f"   Database:   {settings.DB_PATH}")
    logger.info(f"   TTS Voice:  {tts.voice}")
    uvicorn.run(app, host=settings.HOST, port=settings.PORT, log_level="info")
