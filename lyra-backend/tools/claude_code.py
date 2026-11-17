"""Explicitly consented local Claude Code delegation with bounded execution."""

import asyncio
import os
import shutil
from config import settings
from core.execution_policy import ExecutionPolicy, has_execution_consent
from core.errors import safe_error
from tools.shell import _run_process


async def run_claude_code(prompt: str, cwd: str | None = None, dangerously_skip_permissions: bool = False, timeout_seconds: int = 180) -> dict:
    if not has_execution_consent():
        return {"success": False, "error": "Explicit approval is required to delegate to Claude Code."}
    if dangerously_skip_permissions:
        return {"success": False, "error": "Disabling Claude Code permissions is not allowed by this tool."}
    try:
        if not prompt or not prompt.strip():
            raise ValueError("Prompt cannot be empty.")
        binary = settings.CLAUDE_BINARY_PATH
        if not binary or not os.path.isfile(binary):
            binary = shutil.which("claude")
        if not binary:
            return {"success": False, "exit_code": 127, "error": "Claude Code executable was not found. Install and authenticate the CLI first."}
        policy = ExecutionPolicy()
        directory = policy.resolve_path(cwd or policy.default_root)
        if not directory.is_dir():
            raise ValueError("Working directory does not exist.")
        env = {key: value for key, value in os.environ.items() if not key.endswith("_API_KEY") and key not in {"HF_TOKEN", "BACKEND_AUTH_TOKEN"}}
        process = await asyncio.create_subprocess_exec(binary, "-p", prompt.strip(), "--output-format", "text", cwd=str(directory), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env, start_new_session=True)
        result = await _run_process(process, max(0.1, min(float(timeout_seconds), 300)))
        result["output"] = result.get("stdout", "") or result.get("stderr", "")
        return result
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        return {"success": False, "verified": False, "error": safe_error(exc)}
