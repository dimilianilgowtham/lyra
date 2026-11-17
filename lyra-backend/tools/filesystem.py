"""Bounded workspace file tools with credential exclusion and verified atomic writes."""

import hashlib
import asyncio
import os
import re
import tempfile
from pathlib import Path
from core.execution_policy import ExecutionPolicy, PolicyError, has_execution_consent
from core.errors import safe_error

MAX_FILE_SIZE_BYTES = 500 * 1024
MAX_DIRECTORY_ENTRIES = 1000
MAX_SEARCH_FILES = 10000
LYRA_PROJECT_DIR = str(Path(__file__).resolve().parent.parent.parent)


async def read_file(filepath: str, max_lines: int = 500) -> dict:
    try:
        path = ExecutionPolicy().resolve_path(filepath)
        if not path.is_file():
            raise ValueError("File does not exist or is not a regular file.")
        size = path.stat().st_size
        if size > MAX_FILE_SIZE_BYTES:
            raise ValueError(f"File exceeds {MAX_FILE_SIZE_BYTES} byte limit.")
        with path.open("rb") as stream:
            data = stream.read(MAX_FILE_SIZE_BYTES + 1)
        if len(data) > MAX_FILE_SIZE_BYTES:
            raise ValueError("File grew beyond the read limit.")
        lines = data.decode("utf-8", errors="replace").splitlines()
        limit = max(1, min(int(max_lines), 5000))
        return {"success": True, "path": str(path), "content": "\n".join(f"{i + 1:>4} | {line}" for i, line in enumerate(lines[:limit])), "lines": len(lines), "size_bytes": len(data), "truncated": len(lines) > limit, "sha256": hashlib.sha256(data).hexdigest(), "verified": True}
    except Exception as exc:
        return {"success": False, "error": safe_error(exc)}


async def write_file(filepath: str, content: str) -> dict:
    if not has_execution_consent():
        return {"success": False, "error": "Explicit approval is required to write a file."}
    temp_name = None
    try:
        policy = ExecutionPolicy()
        path = policy.resolve_path(filepath)
        data = content.encode("utf-8")
        if len(data) > MAX_FILE_SIZE_BYTES:
            raise ValueError(f"Content exceeds {MAX_FILE_SIZE_BYTES} byte limit.")
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temp_name = tempfile.mkstemp(prefix=".lyra-", dir=str(path.parent))
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        # Recheck containment before committing the atomic rename.
        if policy.resolve_path(filepath) != path:
            raise PolicyError("Destination changed while preparing the write.")
        os.replace(temp_name, path)
        temp_name = None
        with path.open("rb") as stream:
            saved = stream.read(MAX_FILE_SIZE_BYTES + 1)
        expected = hashlib.sha256(data).hexdigest()
        actual = hashlib.sha256(saved).hexdigest()
        verified = actual == expected and len(saved) == len(data)
        return {"success": verified, "verified": verified, "path": str(path), "bytes_written": len(saved), "sha256": actual, "expected_sha256": expected, "error": None if verified else "Readback did not match the requested file content."}
    except Exception as exc:
        return {"success": False, "verified": False, "error": safe_error(exc)}
    finally:
        if temp_name:
            try:
                os.unlink(temp_name)
            except OSError:
                pass


async def list_directory(dirpath: str | None = None) -> dict:
    try:
        policy = ExecutionPolicy()
        path = policy.resolve_path(dirpath or policy.default_root)
        if not path.is_dir():
            raise ValueError("Path is not a directory.")
        entries = []
        truncated = False
        for child in path.iterdir():
            if len(entries) >= MAX_DIRECTORY_ENTRIES:
                truncated = True
                break
            try:
                resolved = policy.resolve_path(child)
            except PolicyError:
                continue
            entries.append({"name": child.name, "type": "directory" if resolved.is_dir() else "file", "size_bytes": resolved.stat().st_size if resolved.is_file() else 0})
        entries.sort(key=lambda entry: (entry["type"] != "directory", entry["name"].lower()))
        return {"success": True, "path": str(path), "entries": entries, "count": len(entries), "truncated": truncated}
    except Exception as exc:
        return {"success": False, "error": safe_error(exc)}


async def search_files(pattern: str, search_path: str | None = None, max_results: int = 50) -> dict:
    """Literal text search. Avoid symlinks, secrets and dependency/build trees."""
    try:
        policy = ExecutionPolicy()
        root = policy.resolve_path(search_path or policy.default_root)
        if not root.is_dir():
            raise ValueError("Search path is not a directory.")
        if not pattern:
            raise ValueError("Search pattern cannot be empty.")
        limit = max(1, min(int(max_results), 200))
        results, scanned = [], 0
        skipped = {"node_modules", "__pycache__", ".venv", "venv", "dist", "build"}
        for directory, dirs, files in os.walk(root, followlinks=False):
            await asyncio.sleep(0)
            dirs[:] = [name for name in dirs if name not in skipped and name.lower() not in policy.SECRET_DIRS and not (Path(directory) / name).is_symlink()]
            for name in files:
                if scanned >= MAX_SEARCH_FILES:
                    return {"success": True, "pattern": pattern, "results": results, "count": len(results), "truncated": True, "files_scanned": scanned}
                candidate = Path(directory) / name
                if candidate.is_symlink():
                    continue
                try:
                    path = policy.resolve_path(candidate)
                    if not path.is_file() or path.stat().st_size > MAX_FILE_SIZE_BYTES:
                        continue
                    scanned += 1
                    if scanned % 10 == 0:
                        await asyncio.sleep(0)
                    with path.open("rb") as stream:
                        data = stream.read(MAX_FILE_SIZE_BYTES + 1)
                    if b"\x00" in data or len(data) > MAX_FILE_SIZE_BYTES:
                        continue
                    for number, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), 1):
                        if pattern in line:
                            results.append({"file": str(path), "line": number, "content": line[:2000]})
                            if len(results) >= limit:
                                return {"success": True, "pattern": pattern, "results": results, "count": len(results), "truncated": True, "files_scanned": scanned}
                except (OSError, PolicyError):
                    continue
        return {"success": True, "pattern": pattern, "results": results, "count": len(results), "truncated": False, "files_scanned": scanned}
    except Exception as exc:
        return {"success": False, "error": safe_error(exc)}
