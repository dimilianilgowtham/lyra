"""
LYRA — Desktop Control (macOS)
App launching, hardware control, file operations — all via native macOS commands.
"""

import asyncio
import logging
import subprocess
from functools import wraps
from core.execution_policy import ExecutionPolicy, has_execution_consent
from tools.shell import _terminate_process_group

logger = logging.getLogger("LYRA.Desktop")

# ── App Launcher ─────────────────────────────────────────────────

APP_MAP = {
    "chrome": "Google Chrome", "safari": "Safari", "firefox": "Firefox",
    "edge": "Microsoft Edge", "vscode": "Visual Studio Code", "code": "Visual Studio Code",
    "terminal": "Terminal", "iterm": "iTerm", "xcode": "Xcode",
    "finder": "Finder", "notes": "Notes", "calendar": "Calendar",
    "mail": "Mail", "reminders": "Reminders", "messages": "Messages",
    "pages": "Pages", "numbers": "Numbers", "keynote": "Keynote",
    "spotify": "Spotify", "music": "Music", "photos": "Photos", "vlc": "VLC",
    "whatsapp": "WhatsApp", "telegram": "Telegram", "discord": "Discord",
    "slack": "Slack", "zoom": "zoom.us", "teams": "Microsoft Teams",
    "calculator": "Calculator", "preview": "Preview",
    "settings": "System Settings", "activity monitor": "Activity Monitor",
}


async def open_app(name: str) -> dict:
    app_name = APP_MAP.get(name.lower().strip(), name)
    try:
        proc = await asyncio.create_subprocess_exec(
            "open", "-a", app_name,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        try:
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            await _terminate_process_group(proc)
            raise
        if proc.returncode == 0:
            return {"success": True, "verified": False, "app": app_name, "action": "launch_requested"}
        return {"success": False, "error": stderr.decode().strip()}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def close_app(name: str) -> dict:
    app_name = APP_MAP.get(name.lower().strip(), name)
    try:
        await _osascript(f'quit app {_apple_string(app_name)}')
        running = await _osascript(f'return application {_apple_string(app_name)} is running')
        verified = running.lower() == "false"
        return {"success": verified, "verified": verified, "app": app_name, "action": "closed" if verified else "quit_requested", "error": None if verified else "The application is still running."}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def switch_app(name: str) -> dict:
    app_name = APP_MAP.get(name.lower().strip(), name)
    try:
        await _osascript(f'tell application {_apple_string(app_name)} to activate')
        return {"success": True, "verified": False, "app": app_name, "action": "activation_requested"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Hardware Control ─────────────────────────────────────────────

def _apple_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").replace("\r", " ") + '"'

async def _osascript(script: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        "osascript", "-e", script,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=8)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        await _terminate_process_group(proc)
        raise
    if proc.returncode != 0:
        raise RuntimeError(stderr.decode(errors="replace").strip()[:1000] or "macOS automation failed.")
    return stdout.decode(errors="replace").strip()[:10000]


async def set_volume(level: int) -> dict:
    level = max(0, min(100, level))
    await _osascript(f"set volume output volume {level}")
    return {"success": True, "action": "volume_set", "level": level}


async def mute() -> dict:
    await _osascript("set volume output muted true")
    return {"success": True, "action": "muted"}


async def unmute() -> dict:
    await _osascript("set volume output muted false")
    return {"success": True, "action": "unmuted"}


async def get_volume() -> dict:
    vol = await _osascript("output volume of (get volume settings)")
    return {"volume": int(vol) if vol.isdigit() else 0}


async def toggle_dark_mode() -> dict:
    await _osascript('tell app "System Events" to tell appearance preferences to set dark mode to not dark mode')
    return {"success": True, "action": "dark_mode_toggled"}


async def get_battery() -> dict:
    proc = await asyncio.create_subprocess_exec(
        "pmset", "-g", "batt",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await proc.communicate()
    output = stdout.decode()
    import re
    pct = re.search(r"(\d+)%", output)
    charging = re.search(r"(charging|discharging|charged)", output, re.I)
    return {
        "percent": int(pct.group(1)) if pct else None,
        "status": charging.group(1).lower() if charging else "unknown",
    }


async def lock_screen() -> dict:
    await _osascript('tell application "System Events" to keystroke "q" using {command down, control down}')
    return {"success": True, "action": "screen_locked"}


async def show_notification(title: str, message: str) -> dict:
    await _osascript(f'display notification {_apple_string(message)} with title {_apple_string(title)}')
    return {"success": True, "action": "notification_shown"}


# ── Browser Control ──────────────────────────────────────────────

async def open_url(url: str) -> dict:
    ExecutionPolicy().validate_tool_paths("open_url", {"url": url})
    proc = await asyncio.create_subprocess_exec("open", url, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, start_new_session=True)
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=8)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        await _terminate_process_group(proc)
        raise
    success = proc.returncode == 0
    return {"success": success, "verified": False, "action": "url_launch_requested" if success else "url_launch_failed", "url": url, "error": None if success else stderr.decode(errors="replace").strip()[:1000] or "Browser launch failed."}


async def web_search(query: str) -> dict:
    import urllib.parse
    url = f"https://www.google.com/search?q={urllib.parse.quote(query)}"
    return await open_url(url)


# ── File & Folder Operations ────────────────────────────────────

async def create_folder(folder_name: str, base_path: str = None) -> dict:
    """Create a folder on the user's Desktop or Documents."""
    from pathlib import Path
    import re as _re

    policy = ExecutionPolicy()
    try:
        base = policy.resolve_path(base_path or policy.default_root)
    except ValueError as exc:
        return {"success": False, "error": str(exc)}

    # Security: reject dangerous folder names
    if ".." in folder_name or "/" in folder_name or _re.search(r"[;&|`$]", folder_name):
        return {"success": False, "error": "Invalid folder name."}

    try:
        full_path = policy.resolve_path(base / folder_name)
        full_path.mkdir(parents=True, exist_ok=True)
        return {"success": full_path.is_dir(), "verified": full_path.is_dir(), "path": str(full_path), "action": "folder_created"}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def open_file_or_folder(path: str) -> dict:
    """Open a file or folder using macOS `open`."""
    from pathlib import Path as _Path

    if ".." in path:
        return {"success": False, "error": "Path traversal not allowed."}

    target = _Path(path).expanduser()
    if not target.exists():
        return {"success": False, "error": f"Path does not exist: {path}"}

    try:
        proc = await asyncio.create_subprocess_exec(
            "open", str(target),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
        if proc.returncode == 0:
            return {"success": True, "path": path, "action": "opened"}
        return {"success": False, "error": stderr.decode().strip()}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def copy_to_clipboard(text: str) -> dict:
    """Copy text to the macOS clipboard via pbcopy."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "pbcopy",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.communicate(input=text.encode())
        return {"success": True, "action": "copied_to_clipboard", "length": len(text)}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def type_text(text: str) -> dict:
    """Simulate typing via AppleScript keystroke. Max 500 chars."""
    if len(text) > 500:
        return {"success": False, "error": "Text exceeds 500-character limit."}

    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    script = f'tell application "System Events" to keystroke "{escaped}"'
    try:
        await _osascript(script)
        return {"success": True, "action": "text_typed", "length": len(text)}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def press_hotkey(keys: str) -> dict:
    """Press a keyboard shortcut (e.g. 'cmd+c', 'ctrl+shift+a')."""
    parts = [k.strip().lower() for k in keys.split("+")]
    if len(parts) < 2:
        return {"success": False, "error": "Need at least modifier+key, e.g. 'cmd+c'."}

    key_char = parts[-1]
    modifiers = parts[:-1]

    mod_map = {
        "cmd": "command down",
        "command": "command down",
        "ctrl": "control down",
        "control": "control down",
        "alt": "option down",
        "option": "option down",
        "shift": "shift down",
    }

    applescript_mods = []
    for m in modifiers:
        mapped = mod_map.get(m)
        if not mapped:
            return {"success": False, "error": f"Unknown modifier: {m}"}
        applescript_mods.append(mapped)

    using_clause = ", ".join(applescript_mods)
    script = f'tell application "System Events" to keystroke "{key_char}" using {{{using_clause}}}'
    try:
        await _osascript(script)
        return {"success": True, "action": "hotkey_pressed", "keys": keys}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def get_active_window() -> dict:
    """Get the name and title of the frontmost application window."""
    try:
        app_name = await _osascript(
            'tell application "System Events" to get name of first application process whose frontmost is true'
        )
        # Try to get window title (may fail for some apps)
        try:
            window_title = await _osascript(
                'tell application "System Events" to get name of front window of (first application process whose frontmost is true)'
            )
        except Exception:
            window_title = ""
        return {"app": app_name, "title": window_title}
    except Exception as e:
        return {"app": "unknown", "title": "", "error": str(e)}


# ── System Info ──────────────────────────────────────────────────

_last_net_time = None
_last_bytes_sent = None
_last_bytes_recv = None


async def get_system_stats() -> dict:
    global _last_net_time, _last_bytes_sent, _last_bytes_recv
    import psutil
    import time

    now = time.time()

    # Calculate network rates in MB/s
    up_speed = 0.0
    down_speed = 0.0
    try:
        net_io = psutil.net_io_counters()
        if _last_net_time is not None:
            elapsed = now - _last_net_time
            if elapsed > 0:
                up_speed = (net_io.bytes_sent - _last_bytes_sent) / elapsed / (1024 * 1024)
                down_speed = (net_io.bytes_recv - _last_bytes_recv) / elapsed / (1024 * 1024)
                if up_speed < 0:
                    up_speed = 0.0
                if down_speed < 0:
                    down_speed = 0.0
        _last_net_time = now
        _last_bytes_sent = net_io.bytes_sent
        _last_bytes_recv = net_io.bytes_recv
    except Exception as e:
        logger.warning(f"Error reading network stats: {e}")

    try:
        uptime = now - psutil.boot_time()
    except Exception:
        uptime = 0.0

    try:
        processes = len(psutil.pids())
    except Exception:
        processes = 0

    return {
        "cpu": psutil.cpu_percent(),
        "memory": psutil.virtual_memory().percent,
        "disk": psutil.disk_usage("/").percent,
        "uptime": uptime,
        "processes": processes,
        "network": {
            "up": up_speed,
            "down": down_speed,
        },
    }


def _consented(handler):
    @wraps(handler)
    async def wrapped(*args, **kwargs):
        if not has_execution_consent():
            return {"success": False, "error": "Explicit approval is required for this desktop change."}
        return await handler(*args, **kwargs)
    return wrapped


for _mutation in ("open_app", "close_app", "switch_app", "set_volume", "mute", "unmute", "toggle_dark_mode", "lock_screen", "show_notification", "open_url", "create_folder", "open_file_or_folder", "copy_to_clipboard", "type_text", "press_hotkey"):
    globals()[_mutation] = _consented(globals()[_mutation])

