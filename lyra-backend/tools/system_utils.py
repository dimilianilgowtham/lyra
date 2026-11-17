"""Native utility tools with checked return codes and cancellable process groups."""

import asyncio
import subprocess
from core.errors import safe_error
from core.execution_policy import has_execution_consent
from tools.shell import _run_process, _terminate_process_group
from desktop.control import _apple_string


async def _native_result(*command, input_text=None):
    process = None
    try:
        process = await asyncio.create_subprocess_exec(*command, stdin=asyncio.subprocess.PIPE if input_text is not None else asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, start_new_session=True)
        if input_text is not None:
            process.stdin.write(input_text.encode("utf-8"))
            await process.stdin.drain()
            process.stdin.close()
        return await _run_process(process, 5)
    except asyncio.CancelledError:
        if process:
            await _terminate_process_group(process)
        raise
    except Exception as exc:
        if process and process.returncode is None:
            await _terminate_process_group(process)
        return {"success": False, "error": safe_error(exc)}


async def get_clipboard(**kwargs):
    result = await _native_result("pbpaste")
    if result.get("success"):
        result["content"] = result.get("stdout", "")
        result["result"] = result["content"]
    return result


async def set_clipboard(text="", **kwargs):
    if not has_execution_consent():
        return {"success": False, "error": "Explicit approval is required to change the clipboard."}
    if len(text.encode("utf-8")) > 500000:
        return {"success": False, "error": "Clipboard text exceeds the size limit."}
    result = await _native_result("pbcopy", input_text=text)
    if result.get("success"):
        result["result"] = f"Copied {len(text)} characters to the clipboard."
    return result


async def send_notification(title="Lyra", message="", **kwargs):
    if not has_execution_consent():
        return {"success": False, "error": "Explicit approval is required to show a notification."}
    script = f'display notification {_apple_string(message)} with title {_apple_string(title)} sound name "Glass"'
    result = await _native_result("osascript", "-e", script)
    if result.get("success"):
        result["result"] = "The notification request was accepted by macOS."
    return result


async def get_wifi_info(**kwargs):
    result = await _native_result("/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport", "-I")
    if result.get("success"):
        result["result"] = result.get("stdout", "").strip()
    return result


async def get_battery_info(**kwargs):
    result = await _native_result("pmset", "-g", "batt")
    if result.get("success"):
        result["result"] = result.get("stdout", "").strip()
    return result
