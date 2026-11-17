"""
LYRA — Intent Router v2.0
Classifies user commands and routes them to the right handler.
CRITICAL: Knowledge questions go to AI chat, NOT to Chrome.
"""

import re
import logging
from desktop import control

logger = logging.getLogger("LYRA.Router")


class IntentRouter:
    """Classifies and routes user commands with intelligent priority ordering."""

    @staticmethod
    async def route(text: str) -> dict:
        """
        Classify a command and execute it.
        Returns {category, action, result, speak}.

        Priority order (IMPORTANT — order matters!):
          1. Empty → reject
          2. Greetings → AI chat (warm personality response)
          3. Hardware commands → direct OS execution
          4. App open/close/switch → direct OS execution
          5. Explicit URL navigation → open browser
          6. RAG-specific triggers → RAG pipeline
          7. EVERYTHING ELSE → AI chat (the AI answers from knowledge)

        The key insight: we NEVER route knowledge questions to Chrome.
        "What is X?", "Tell me about Y", "Latest AI news" → AI chat.
        The AI is smart enough to answer. That's the whole point.
        """
        lower = text.lower().strip()
        if not lower:
            return {"category": "empty", "speak": "I didn't catch that."}

        # ── 1. Greetings → AI chat ──────────────────────────────────
        if re.match(
            r"^(hi|hello|hey|good morning|good evening|good afternoon|how are you"
            r"|what'?s up|help|yo|sup|howdy)\b",
            lower,
        ):
            return {"category": "chat", "speak": None}

        # ── 2. Hardware / System Commands → Direct execution ────────
        # These are unambiguous OS-level actions.

        # Volume
        if "mute" in lower and "unmute" not in lower:
            r = await control.mute()
            return {"category": "hardware", "speak": "Volume muted.", "result": r}
        if "unmute" in lower:
            r = await control.unmute()
            return {"category": "hardware", "speak": "Volume unmuted.", "result": r}
        m = re.search(r"volume\s*(?:to\s*)?(\d+)", lower)
        if m:
            r = await control.set_volume(int(m.group(1)))
            return {"category": "hardware", "speak": f"Volume set to {m.group(1)} percent.", "result": r}
        if "volume up" in lower:
            v = await control.get_volume()
            r = await control.set_volume(min(100, v.get("volume", 50) + 15))
            return {"category": "hardware", "speak": "Volume up.", "result": r}
        if "volume down" in lower:
            v = await control.get_volume()
            r = await control.set_volume(max(0, v.get("volume", 50) - 15))
            return {"category": "hardware", "speak": "Volume down.", "result": r}

        # Dark mode
        if "dark mode" in lower or "light mode" in lower:
            r = await control.toggle_dark_mode()
            return {"category": "hardware", "speak": "Display mode toggled.", "result": r}

        # Battery
        if re.match(r"^(battery|check battery|battery status|how much battery)", lower):
            r = await control.get_battery()
            pct = r.get("percent")
            status = r.get("status", "unknown")
            speak = f"Battery is at {pct} percent, {status}." if pct else "Couldn't get battery status."
            return {"category": "hardware", "speak": speak, "result": r}

        # Lock screen
        if "lock" in lower and ("screen" in lower or "computer" in lower or "mac" in lower):
            r = await control.lock_screen()
            return {"category": "hardware", "speak": "Screen locked.", "result": r}

        # System stats (explicit request)
        if re.match(r"^(system status|system info|check system|show stats|cpu usage|memory usage|ram usage|disk usage|system vitals)", lower):
            r = await control.get_system_stats()
            cpu = round(r.get("cpu", r.get("cpu_percent", 0)))
            mem_data = r.get("memory", 0)
            mem = round(mem_data if isinstance(mem_data, (int, float)) else mem_data.get("percent", 0) if isinstance(mem_data, dict) else 0)
            disk = round(r.get("disk", 0)) if isinstance(r.get("disk"), (int, float)) else 0
            return {"category": "system", "speak": f"CPU is at {cpu} percent, memory is at {mem} percent, and disk is at {disk} percent.", "result": r}

        # Screenshot / display capture
        if any(w in lower for w in ["take a screenshot", "take screenshot", "capture screen", "screenshot"]):
            from tools.vision import take_screenshot
            r = await take_screenshot()
            speak = "Screenshot captured." if r.get("success") else f"Failed to take screenshot: {r.get('error', 'unknown')}"
            return {"category": "hardware", "speak": speak, "result": r}

        # Create folder
        folder_match = re.match(r"(?:create|make|new)\s+(?:a\s+)?(?:folder|directory)\s+(?:called|named\s+)?([a-zA-Z0-9_\-\s]+)", lower)
        if folder_match:
            folder_name = folder_match.group(1).strip()
            r = await control.create_folder(folder_name)
            speak = f"Created folder {folder_name} on your Desktop." if r.get("success") else f"Could not create folder: {r.get('error', '')}"
            return {"category": "file", "speak": speak, "result": r}

        # Active frontmost window
        if any(w in lower for w in ["active window", "front window", "current window", "what window is this"]):
            r = await control.get_active_window()
            app = r.get("app", "unknown")
            title = r.get("title", "")
            speak = f"Frontmost application is {app}{': ' + title if title else ''}."
            return {"category": "system", "speak": speak, "result": r}

        # WiFi info
        if re.match(r"^(wifi|check wifi|wifi status|network info|wifi name)", lower):
            from tools.system_utils import get_wifi_info
            r = await get_wifi_info()
            return {"category": "hardware", "speak": "Retrieved Wi-Fi network information.", "result": r}

        # ── 3. App Management → Direct execution ───────────────────

        # Close/quit app (check before open to avoid "close" matching "open" logic)
        app_close = re.match(r"(close|quit|exit|kill)\s+(.+)", lower)
        if app_close:
            app = app_close.group(2).strip()
            r = await control.close_app(app)
            return {"category": "app", "speak": f"Closing {app}.", "result": r}

        # Switch to app
        app_switch = re.match(r"(switch to|go to|focus|activate)\s+(.+)", lower)
        if app_switch:
            app = app_switch.group(2).strip()
            # Don't match "go to google.com" — that's a URL
            if not re.search(r"\.\w{2,}", app):
                r = await control.switch_app(app)
                return {"category": "app", "speak": f"Switching to {app}.", "result": r}

        # Open app (but NOT URLs or knowledge questions)
        app_open = re.match(r"(open|launch|start|run)\s+(.+)", lower)
        if app_open:
            target = app_open.group(2).strip()

            # Check if it's a URL → open in browser
            if re.search(r"(https?://|www\.|\.com|\.org|\.net|\.io|\.dev|\.ai)", target):
                url = target
                if not url.startswith("http"):
                    url = "https://" + url
                r = await control.open_url(url)
                return {"category": "web", "speak": f"Opening {target}.", "result": r}

            # Check if it's a well-known website name
            website_map = {
                "youtube": "https://youtube.com",
                "github": "https://github.com",
                "twitter": "https://x.com",
                "reddit": "https://reddit.com",
                "gmail": "https://mail.google.com",
                "google": "https://google.com",
                "stackoverflow": "https://stackoverflow.com",
                "chatgpt": "https://chat.openai.com",
                "linkedin": "https://linkedin.com",
            }
            if target in website_map:
                r = await control.open_url(website_map[target])
                return {"category": "web", "speak": f"Opening {target}.", "result": r}

            # Otherwise it's an app
            r = await control.open_app(target)
            speak = f"Opening {target}." if r.get("success") else f"Couldn't open {target}."
            return {"category": "app", "speak": speak, "result": r}

        # ── 4. Explicit URL Navigation ─────────────────────────────
        url_match = re.match(
            r"(go to|visit|navigate to|browse)\s+(https?://\S+|www\.\S+|\S+\.(com|org|net|io|dev|ai)\S*)",
            lower,
        )
        if url_match:
            url = url_match.group(2)
            if not url.startswith("http"):
                url = "https://" + url
            r = await control.open_url(url)
            return {"category": "web", "speak": f"Opening {url_match.group(2)}.", "result": r}

        # ── 5. RAG-Specific Triggers → RAG pipeline ────────────────
        # Only trigger RAG for explicit codebase/git search requests
        rag_match = re.match(
            r"(?:search|find|look up|grep|scan|check)\s+"
            r"(?:(?:the|my|our|in|through)\s+)?"
            r"(codebase|code|local|files?|git|commits?|history|repo|repository|project|source)\s+"
            r"(?:for|about|containing|with|regarding)\s+(.+)",
            lower,
        )
        if rag_match:
            source_hint = rag_match.group(1)
            query = rag_match.group(2).strip().strip("\"'")
            sources = []
            if source_hint in ("git", "commits", "commit", "history", "repo", "repository"):
                sources = ["git"]
            elif source_hint in ("codebase", "code", "local", "file", "files", "project", "source"):
                sources = ["local", "git"]
            else:
                sources = ["local", "git", "web"]
            return {"category": "rag", "query": query, "sources": sources, "speak": None}

        rag_all = re.match(r"(?:rag|deep)\s+(?:search|find|query)\s+(.+)", lower)
        if rag_all:
            return {
                "category": "rag",
                "query": rag_all.group(1).strip(),
                "sources": ["local", "git", "web"],
                "speak": None,
            }

        # ── 6. Claude Code Autonomous Developer Intent ─────────────
        claude_match = re.match(
            r"^(?:run\s+claude(?:\s+code)?|use\s+claude(?:\s+code)?|ask\s+claude(?:\s+code)?|claude\s+code)\s*(?:to\s*)?(.+)",
            lower,
            re.IGNORECASE,
        )
        if claude_match:
            claude_prompt = claude_match.group(1).strip()
            return {"category": "claude_code", "prompt": claude_prompt, "speak": None}

        # ── 7. Agentic & Autonomous Technical Tasks ────────────────
        if (
            lower.startswith(("agent:", "task:", "automate:", "run agent", "execute script", "write a file", "create a file", "inspect file"))
            or re.search(r"\b(write|create|modify|edit)\s+(?:a\s+)?(?:script|file|component|code)\b", lower)
        ):
            return {"category": "agent", "query": text, "speak": None}

        # ── 8. EVERYTHING ELSE → AI Chat ───────────────────────────
        # Questions, technical discussions, brainstorming — ALL go to the AI brain.
        return {"category": "chat", "speak": None}
