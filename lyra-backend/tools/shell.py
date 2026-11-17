"""Consented shell execution with process-group cleanup; not an OS sandbox."""

import asyncio
import os
import signal
import time
from pathlib import Path
from core.execution_policy import ExecutionPolicy, has_execution_consent
from core.errors import safe_error

MAX_OUTPUT_CHARS = 10000


async def _terminate_process_group(process):
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    await process.wait()


async def _bounded_stream(stream, limit=MAX_OUTPUT_CHARS):
    chunks, retained, total = [], 0, 0
    while True:
        chunk = await stream.read(8192)
        if not chunk:
            break
        total += len(chunk)
        if retained < limit:
            keep = chunk[:limit - retained]
            chunks.append(keep)
            retained += len(keep)
    return b"".join(chunks).decode("utf-8", errors="replace"), total > retained


async def _run_process(process, timeout):
    readers = [asyncio.create_task(_bounded_stream(process.stdout)), asyncio.create_task(_bounded_stream(process.stderr))]
    combined = asyncio.gather(*readers, process.wait())
    try:
        result = await asyncio.wait_for(asyncio.shield(combined), timeout=timeout)
        (stdout, stdout_truncated), (stderr, stderr_truncated), _ = result
        return {"success": process.returncode == 0, "exit_code": process.returncode, "stdout": stdout, "stderr": stderr, "stdout_truncated": stdout_truncated, "stderr_truncated": stderr_truncated, "verified": False, "verification": "process_exit_only", "error": None if process.returncode == 0 else f"Process exited with code {process.returncode}."}
    except asyncio.CancelledError:
        await _terminate_process_group(process)
        raise
    except asyncio.TimeoutError:
        await _terminate_process_group(process)
        (stdout, out_cut), (stderr, err_cut), _ = await combined
        return {"success": False, "verified": False, "exit_code": process.returncode, "stdout": stdout, "stderr": stderr, "stdout_truncated": out_cut, "stderr_truncated": err_cut, "timed_out": True, "error": f"Process timed out after {timeout} seconds; its process group was terminated."}
    finally:
        for reader in readers:
            if not reader.done():
                reader.cancel()
        await asyncio.gather(*readers, return_exceptions=True)
        await asyncio.gather(combined, return_exceptions=True)


async def execute_command(command: str, cwd: str | None = None, timeout: int = 30) -> dict:
    if not has_execution_consent():
        return {"success": False, "error": "Explicit approval is required to run shell commands."}
    try:
        if not command or not command.strip():
            raise ValueError("Command cannot be empty.")
        policy = ExecutionPolicy()
        directory = policy.resolve_path(cwd or policy.default_root)
        if not directory.is_dir():
            raise ValueError("Working directory does not exist.")
        # Apps launched by Finder often lack Homebrew and user CLI locations.
        # Do not source shell startup files or hand provider credentials to tools.
        environment = {key: value for key, value in os.environ.items()
                       if not key.upper().endswith('_API_KEY') and key.upper() not in {'HF_TOKEN', 'BACKEND_AUTH_TOKEN'}}
        paths = environment.get('PATH', '/usr/bin:/bin:/usr/sbin:/sbin').split(os.pathsep)
        for candidate in (Path.home() / '.local/bin', Path('/opt/homebrew/bin'), Path('/usr/local/bin')):
            if candidate.is_dir() and str(candidate) not in paths:
                paths.append(str(candidate))
        environment['PATH'] = os.pathsep.join(paths)
        started = time.monotonic()
        process = await asyncio.create_subprocess_shell(command, cwd=str(directory), env=environment, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, start_new_session=True)
        result = await _run_process(process, max(0.1, min(float(timeout), 300)))
        return {**result, 'command': command, 'cwd': str(directory), 'duration_ms': round((time.monotonic() - started) * 1000, 2)}
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        return {"success": False, "verified": False, "error": safe_error(exc)}
