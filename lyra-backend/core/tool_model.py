"""Server-only model transport for structured tool turns and provider failover."""

import json
import uuid
import httpx
from core.errors import safe_error


class ModelProviderError(RuntimeError):
    pass


class ToolModelCaller:
    OPENAI_PROVIDERS = {
        "groq": ("GROQ_API_KEY", "https://api.groq.com/openai/v1/chat/completions", "llama-3.3-70b-versatile"),
        "openai": ("OPENAI_API_KEY", "https://api.openai.com/v1/chat/completions", "gpt-4o-mini"),
        "openrouter": ("OPENROUTER_API_KEY", "https://openrouter.ai/api/v1/chat/completions", "openai/gpt-4o-mini"),
        "nvidia": ("NVIDIA_API_KEY", "https://integrate.api.nvidia.com/v1/chat/completions", "meta/llama-3.3-70b-instruct"),
    }
    ORDER = ("groq", "openai", "openrouter", "nvidia", "anthropic", "gemini", "ollama")

    def __init__(self, *, settings_obj=None, transport=None, timeout=30.0):
        if settings_obj is None:
            from config import settings
            settings_obj = settings
        self.settings = settings_obj
        self.transport = transport
        self.timeout = timeout

    def _available(self, provider):
        if provider == "ollama":
            return bool(getattr(self.settings, "OLLAMA_BASE_URL", ""))
        return bool(getattr(self.settings, f"{provider.upper()}_API_KEY", ""))

    async def __call__(self, messages, tools, *, provider=None, model=None):
        preferred = provider if provider in self.ORDER else None
        if not preferred and model:
            if model.startswith("gemini"):
                preferred = "gemini"
            elif model.startswith("gpt"):
                preferred = "openai"
            elif model.startswith("claude"):
                preferred = "anthropic"
            elif "/" in model:
                preferred = "openrouter"
        order = ([preferred] if preferred else []) + [p for p in self.ORDER if p != preferred]
        errors = []
        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            for name in order:
                if not self._available(name):
                    continue
                # A model identifier is provider-specific; fallback uses its own default.
                target_model = model if name == preferred else None
                try:
                    if name == "gemini":
                        result = await self._gemini(client, messages, tools, target_model)
                    elif name == "anthropic":
                        result = await self._anthropic(client, messages, tools, target_model)
                    else:
                        result = await self._openai(client, name, messages, tools, target_model)
                    if not result.get("content") and not result.get("tool_calls"):
                        raise ValueError("Empty model response")
                    result["provider"] = name
                    return result
                except httpx.HTTPStatusError as exc:
                    errors.append(f"{name}: HTTP {exc.response.status_code}")
                except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                    # Never expose authorization headers, provider error bodies or key URLs.
                    errors.append(f"{name}: {type(exc).__name__}")
        detail = safe_error("; ".join(errors) or "no provider is configured")
        raise ModelProviderError(f"No model provider could complete the tool turn ({detail}).")

    async def _openai(self, client, provider, messages, tools, model):
        if provider == "ollama":
            endpoint = self.settings.OLLAMA_BASE_URL.rstrip("/") + "/v1/chat/completions"
            model = model or getattr(self.settings, "DEFAULT_LOCAL_MODEL", "llama3.2")
            headers = {}
        else:
            key_name, endpoint, default_model = self.OPENAI_PROVIDERS[provider]
            model = model or getattr(self.settings, f"{provider.upper()}_TOOL_MODEL", default_model)
            headers = {"Authorization": f"Bearer {getattr(self.settings, key_name)}"}
        payload = {"model": model, "messages": messages, "temperature": 0.2, "max_tokens": 2500}
        if tools:
            payload.update(tools=tools, tool_choice="auto")
        response = await client.post(endpoint, headers=headers, json=payload)
        response.raise_for_status()
        message = response.json()["choices"][0]["message"]
        calls = []
        for call in message.get("tool_calls") or []:
            function = call["function"]
            calls.append({"id": call.get("id") or str(uuid.uuid4()), "name": function["name"], "arguments": function.get("arguments", "{}")})
        return {"content": message.get("content") or "", "tool_calls": calls, "model": model}

    async def _gemini(self, client, messages, tools, model):
        model = model or getattr(self.settings, "GEMINI_TOOL_MODEL", "gemini-2.0-flash")
        contents, call_names = [], {}
        for message in messages:
            role = message["role"]
            if role == "system":
                continue
            parts = []
            if role == "tool":
                name = call_names[message["tool_call_id"]]
                parts = [{"functionResponse": {"name": name, "response": json.loads(message["content"])}}]
            else:
                if message.get("content"):
                    parts.append({"text": message["content"]})
                for call in message.get("tool_calls") or []:
                    function = call["function"]
                    call_names[call["id"]] = function["name"]
                    parts.append({"functionCall": {"name": function["name"], "args": json.loads(function["arguments"])}})
            if parts:
                contents.append({"role": "model" if role == "assistant" else "user", "parts": parts})
        payload = {"contents": contents, "system_instruction": {"parts": [{"text": messages[0]["content"]}]}, "generationConfig": {"maxOutputTokens": 2500, "temperature": 0.2}}
        if tools:
            declarations = []
            for tool in tools:
                declaration = dict(tool["function"])
                declaration["parameters"] = self._gemini_schema(declaration["parameters"])
                declarations.append(declaration)
            payload["tools"] = [{"function_declarations": declarations}]
        response = await client.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent", headers={"x-goog-api-key": self.settings.GEMINI_API_KEY}, json=payload)
        response.raise_for_status()
        parts = response.json()["candidates"][0]["content"]["parts"]
        calls = [{"id": str(uuid.uuid4()), "name": p["functionCall"]["name"], "arguments": p["functionCall"].get("args", {})} for p in parts if "functionCall" in p]
        return {"content": "\n".join(p["text"] for p in parts if "text" in p), "tool_calls": calls, "model": model}

    @classmethod
    def _gemini_schema(cls, value):
        if isinstance(value, dict):
            return {k: cls._gemini_schema(v) for k, v in value.items() if k not in {"additionalProperties", "$schema"}}
        if isinstance(value, list):
            return [cls._gemini_schema(v) for v in value]
        return value

    async def _anthropic(self, client, messages, tools, model):
        model = model or getattr(self.settings, "ANTHROPIC_TOOL_MODEL", "claude-sonnet-4-20250514")
        converted = []
        for message in messages:
            if message["role"] == "system":
                continue
            role = "assistant" if message["role"] == "assistant" else "user"
            blocks = []
            if message["role"] == "tool":
                blocks.append({"type": "tool_result", "tool_use_id": message["tool_call_id"], "content": message["content"]})
            else:
                if message.get("content"):
                    blocks.append({"type": "text", "text": message["content"]})
                for call in message.get("tool_calls") or []:
                    blocks.append({"type": "tool_use", "id": call["id"], "name": call["function"]["name"], "input": json.loads(call["function"]["arguments"])})
            if converted and converted[-1]["role"] == role:
                converted[-1]["content"].extend(blocks)
            else:
                converted.append({"role": role, "content": blocks})
        payload = {"model": model, "system": messages[0]["content"], "messages": converted, "max_tokens": 2500}
        if tools:
            payload["tools"] = [{"name": t["function"]["name"], "description": t["function"]["description"], "input_schema": t["function"]["parameters"]} for t in tools]
        response = await client.post("https://api.anthropic.com/v1/messages", headers={"x-api-key": self.settings.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01"}, json=payload)
        response.raise_for_status()
        blocks = response.json()["content"]
        calls = [{"id": b["id"], "name": b["name"], "arguments": b["input"]} for b in blocks if b["type"] == "tool_use"]
        return {"content": "\n".join(b["text"] for b in blocks if b["type"] == "text"), "tool_calls": calls, "model": model}
