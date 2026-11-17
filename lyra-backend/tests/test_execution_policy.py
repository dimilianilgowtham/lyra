import hashlib
import sys
import tempfile
import unittest
import asyncio
import os
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class ExecutionPolicyTests(unittest.IsolatedAsyncioTestCase):
    async def test_policy_exists_and_bounds_canonical_paths(self):
        import importlib.util
        self.assertIsNotNone(importlib.util.find_spec("core.execution_policy"), "file access needs a canonical workspace policy")
        from core.execution_policy import ExecutionPolicy, PolicyError
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "workspace"
            outside = Path(temp) / "private"
            root.mkdir()
            outside.mkdir()
            (root / "escape").symlink_to(outside, target_is_directory=True)
            policy = ExecutionPolicy([root])
            self.assertEqual(policy.resolve_path(root / "safe.txt"), (root / "safe.txt").resolve())
            for target in [outside / "x", root / "escape" / "x", root / ".env", root / ".ssh" / "id_rsa", root / "private.pem"]:
                with self.assertRaises(PolicyError):
                    policy.resolve_path(target)

    async def test_atomic_write_receipt_contains_verified_hash(self):
        from core.agent_executor import AgentExecutor
        from core.tool_registry import ToolDefinition, ToolRegistry
        from tools.filesystem import write_file
        from config import settings
        registry = ToolRegistry()
        registry.register(ToolDefinition("write_file", "write", {"type": "object", "properties": {"filepath": {"type": "string"}, "content": {"type": "string"}}, "required": ["filepath", "content"]}, write_file, True))
        agent = AgentExecutor(registry)
        self.assertTrue(hasattr(agent, "execute_tool"))
        async def approval(event):
            agent.resolve_approval(event["request_id"], True, "owner")
        with tempfile.TemporaryDirectory() as temp, patch.object(settings, "WORKSPACE_ROOTS", (Path(temp),), create=True):
            path = Path(temp) / "note.txt"
            receipt = await agent.execute_tool("write_file", {"filepath": str(path), "content": "actual saved text"}, "owner", on_approval_request=approval)
            self.assertTrue(receipt["success"])
            self.assertTrue(receipt["verified"])
            self.assertEqual(receipt["result"]["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(path.read_text(), "actual saved text")
            self.assertEqual(list(Path(temp).glob(".lyra-*")), [])

    async def test_read_and_search_do_not_export_secrets(self):
        from config import settings
        from tools.filesystem import read_file, search_files
        with tempfile.TemporaryDirectory() as temp, patch.object(settings, "WORKSPACE_ROOTS", (Path(temp),), create=True):
            root = Path(temp)
            (root / ".env").write_text("SEARCH_TOKEN=hidden")
            (root / "public.py").write_text("SEARCH_TOKEN=visible")
            result = await read_file(str(root / ".env"))
            self.assertFalse(result["success"])
            result = await search_files("SEARCH_TOKEN", str(root))
            self.assertTrue(result["success"])
            self.assertEqual(len(result["results"]), 1)
            self.assertEqual(result["results"][0]["file"], str((root / "public.py").resolve()))

    async def test_shell_requires_explicit_execution_consent(self):
        from tools.shell import execute_command
        result = await execute_command("printf unauthorized")
        self.assertFalse(result["success"])
        self.assertIn("approval", result["error"].lower())

    async def test_shell_timeout_kills_the_spawned_process_group(self):
        from tools.shell import execute_command
        from core.execution_policy import approved_tool_context
        from config import settings
        with tempfile.TemporaryDirectory() as temp, patch.object(settings, "WORKSPACE_ROOTS", (Path(temp),), create=True):
            pid_file = Path(temp) / "child.pid"
            command = f"sleep 30 & child=$!; printf '%s' \"$child\" > '{pid_file}'; wait"
            with approved_tool_context(True):
                result = await execute_command(command, temp, timeout=0.1)
            self.assertFalse(result["success"])
            self.assertIn("terminated", result["error"])
            pid = int(pid_file.read_text())
            await asyncio.sleep(0.05)
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)

    async def test_shell_cancellation_kills_the_spawned_process_group(self):
        from tools.shell import execute_command
        from core.execution_policy import approved_tool_context
        from config import settings
        with tempfile.TemporaryDirectory() as temp, patch.object(settings, "WORKSPACE_ROOTS", (Path(temp),), create=True):
            pid_file = Path(temp) / "child.pid"
            command = f"sleep 30 & child=$!; printf '%s' \"$child\" > '{pid_file}'; wait"
            with approved_tool_context(True):
                task = asyncio.create_task(execute_command(command, temp))
            for _ in range(100):
                if pid_file.exists():
                    break
                await asyncio.sleep(0.01)
            self.assertTrue(pid_file.exists())
            pid = int(pid_file.read_text())
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            await asyncio.sleep(0.05)
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)

    async def test_native_script_nonzero_exit_is_a_failure(self):
        from desktop.control import _osascript
        from unittest.mock import AsyncMock
        fake_process = AsyncMock()
        fake_process.returncode = 1
        fake_process.communicate.return_value = (b"", b"Automation permission denied")
        with patch("desktop.control.asyncio.create_subprocess_exec", return_value=fake_process):
            with self.assertRaises(RuntimeError):
                await _osascript("set volume output volume 20")

    async def test_native_url_launch_nonzero_exit_is_a_failure(self):
        from desktop.control import open_url
        from core.execution_policy import approved_tool_context
        from unittest.mock import AsyncMock
        fake_process = AsyncMock()
        fake_process.returncode = 1
        fake_process.communicate.return_value = (b"", b"Browser unavailable")
        with patch("desktop.control.asyncio.create_subprocess_exec", return_value=fake_process), approved_tool_context(True):
            receipt = await open_url("https://example.com")
        self.assertFalse(receipt["success"])

    async def test_native_utilities_nonzero_exit_is_failed(self):
        import subprocess
        from tools import system_utils
        from core.execution_policy import approved_tool_context
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        for name, args in [("get_clipboard", {}), ("set_clipboard", {"text": "test"}), ("send_notification", {"message": "test"}), ("get_wifi_info", {}), ("get_battery_info", {})]:
            with self.subTest(tool=name):
                stdout = asyncio.StreamReader()
                stderr = asyncio.StreamReader()
                stdout.feed_eof()
                stderr.feed_data(b"Native command rejected")
                stderr.feed_eof()
                process = SimpleNamespace(returncode=7, stdout=stdout, stderr=stderr, stdin=SimpleNamespace(write=lambda data: None, drain=AsyncMock(), close=lambda: None), wait=AsyncMock(return_value=7), communicate=AsyncMock(return_value=(b"", b"Native command rejected")))
                with patch("tools.system_utils.subprocess.run", return_value=subprocess.CompletedProcess([], 7, stdout="", stderr="Native command rejected")), patch("tools.system_utils.asyncio.create_subprocess_exec", return_value=process), approved_tool_context(True):
                    receipt = await getattr(system_utils, name)(**args)
                self.assertFalse(receipt["success"])
                self.assertEqual(receipt["exit_code"], 7)

    async def test_notification_quotes_are_data(self):
        from desktop.control import _apple_string
        self.assertEqual(_apple_string('title" & dangerous'), '"title\\" & dangerous"')

    async def test_injected_policy_is_used_by_the_file_handler(self):
        from core.agent_executor import AgentExecutor
        from core.tool_registry import ToolDefinition, ToolRegistry
        from core.execution_policy import ExecutionPolicy
        from tools.filesystem import write_file
        with tempfile.TemporaryDirectory() as temp:
            registry = ToolRegistry()
            registry.register(ToolDefinition("write_file", "write", {"type": "object", "properties": {"filepath": {"type": "string"}, "content": {"type": "string"}}, "required": ["filepath", "content"]}, write_file, True))
            agent = AgentExecutor(registry, policy=ExecutionPolicy([temp]))
            async def approve(event):
                agent.resolve_approval(event["request_id"], True, "owner")
            receipt = await agent.execute_tool("write_file", {"filepath": str(Path(temp) / "note.txt"), "content": "checked"}, "owner", on_approval_request=approve)
            self.assertTrue(receipt["success"], receipt)


if __name__ == "__main__":
    unittest.main()
