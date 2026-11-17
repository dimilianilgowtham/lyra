"""Durable task lifecycle and conversation migration regressions."""
import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.database import DatabaseManager
try:
    from core.task_runtime import TaskRuntime
except ImportError:
    TaskRuntime = None


class TaskRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = DatabaseManager(str(Path(self.directory.name) / "tasks.db"))
        self.runtimes = []

    async def asyncTearDown(self):
        for runtime in self.runtimes:
            await runtime.shutdown()
        self.directory.cleanup()

    def runtime(self, runner, **kwargs):
        self.assertIsNotNone(TaskRuntime, "TaskRuntime must exist")
        runtime = TaskRuntime(self.db, runner, **kwargs)
        self.runtimes.append(runtime)
        return runtime

    async def terminal(self, runtime, task_id):
        for _ in range(100):
            task = runtime.get(task_id)
            if task["status"] in {"completed", "failed", "cancelled", "interrupted"}:
                return task
            await asyncio.sleep(.001)
        self.fail("Task did not settle")

    async def test_completed_task_and_ordered_events_survive_reopen(self):
        notified = []
        async def runner(task, on_event):
            await on_event("token", {"content": "hello"})
            await on_event("tool_status", {"tool": "read_file", "status": "completed", "receipt": {"success": True, "result": {"content": "file"}}})
            return {"status": "completed", "response": "hello", "tool_calls": []}
        runtime = self.runtime(runner, notify=lambda task, event: notified.append(event))
        task = runtime.create("Read my file", model="model", provider="local")
        self.assertEqual(task["status"], "queued")
        settled = await self.terminal(runtime, task["id"])
        self.assertEqual(settled["status"], "completed")
        self.assertEqual(settled["result"]["response"], "hello")
        events = runtime.events(task["id"])
        self.assertEqual([event["seq"] for event in events], list(range(1, len(events) + 1)))
        self.assertTrue(any(event["type"] == "token" for event in events))
        self.assertTrue(notified)
        reopened = TaskRuntime(DatabaseManager(str(self.db.db_path)), runner)
        self.runtimes.append(reopened)
        self.assertEqual(reopened.get(task["id"])["result"], settled["result"])
        self.assertEqual(reopened.events(task["id"]), events)

    async def test_failed_tool_receipt_cannot_be_reported_completed(self):
        async def runner(task, on_event):
            await on_event("tool_status", {"tool": "write_file", "status": "failed", "receipt": {"success": False, "error": "Denied"}})
            return {"status": "completed", "response": "Done", "tool_calls": [{"success": False, "error": "Denied"}]}
        runtime = self.runtime(runner)
        task = runtime.create("Write")
        settled = await self.terminal(runtime, task["id"])
        self.assertEqual(settled["status"], "failed")
        self.assertIn("Denied", settled["error"])
        self.assertEqual(settled["result"]["status"], "failed")
        response_event = [e for e in runtime.events(task["id"]) if e["type"] == "agent_response"][-1]
        self.assertEqual(response_event["payload"]["status"], "failed")

    async def test_in_progress_receipts_do_not_invalidate_later_success(self):
        async def runner(task, on_event):
            for status in ("pending", "running", "completed"):
                await on_event("tool_status", {"tool": "read_file", "status": status, "receipt": {"status": status, "success": status == "completed", "result": {"content": "Read"} if status == "completed" else {}}})
            return {"status": "completed", "response": "Read", "tool_calls": [{"success": True}]}
        runtime = self.runtime(runner)
        task = runtime.create("Read")
        self.assertEqual((await self.terminal(runtime, task["id"]))["status"], "completed")

    async def test_budget_exhaustion_is_not_completion(self):
        async def runner(task, on_event):
            return {"status": "budget_exhausted", "response": "Partial progress", "tool_calls": []}
        runtime = self.runtime(runner)
        task = runtime.create("Keep working", max_steps=3)
        settled = await self.terminal(runtime, task["id"])
        self.assertEqual(settled["status"], "failed")
        self.assertEqual(settled["metadata"]["max_steps"], 3)

    async def test_cancellation_keeps_receipts_even_when_runner_swallows_cancel(self):
        ready = asyncio.Event()
        async def runner(task, on_event):
            await on_event("tool_status", {"tool": "write_file", "arguments": {"path": "created.txt"}, "status": "completed", "receipt": {"success": True, "result": {"path": "created.txt"}}})
            ready.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                return {"status": "completed", "response": "Partial work", "tool_calls": []}
        runtime = self.runtime(runner)
        task = runtime.create("Do two steps")
        await ready.wait()
        cancelled = await runtime.cancel(task["id"])
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(runtime.get(task["id"])["status"], "cancelled")
        self.assertEqual(runtime.get(task["id"])["result"]["status"], "cancelled")
        self.assertTrue(runtime.get(task["id"])["checkpoint"]["completed_tool_calls"])

    async def test_restart_requires_resume_and_passes_real_evidence(self):
        ready = asyncio.Event()
        async def first_runner(task, on_event):
            await on_event("tool_status", {"tool": "read_file", "status": "completed", "receipt": {"success": True, "result": {"content": "facts"}}})
            ready.set()
            await asyncio.Event().wait()
        first = self.runtime(first_runner)
        task = first.create("Research")
        await ready.wait()
        await first.shutdown()
        captured = []
        async def resumed_runner(task, on_event):
            captured.append(task)
            return {"status": "completed", "response": "Resumed with facts", "tool_calls": []}
        second = self.runtime(resumed_runner)
        self.assertEqual(second.get(task["id"])["status"], "interrupted")
        self.assertFalse(captured)
        second.resume(task["id"])
        await self.terminal(second, task["id"])
        context = captured[0]["resume_context"]
        self.assertEqual(context["completed_tool_calls"][0]["receipt"]["result"]["content"], "facts")
        self.assertTrue(context["events"])

    async def test_approval_resolution_is_scoped_and_expired_after_cancel(self):
        ready = asyncio.Event()
        finish = asyncio.Event()
        calls = []
        async def runner(task, on_event):
            await on_event("tool_approval_request", {"request_id": "request-1", "tool": "delete_file"})
            ready.set()
            await finish.wait()
            return {"status": "completed", "response": "Done", "tool_calls": []}
        def resolve(request_id, approved, owner_id):
            calls.append((request_id, approved, owner_id))
            finish.set()
            return True
        runtime = self.runtime(runner, approval_resolver=resolve)
        task = runtime.create("Delete")
        await ready.wait()
        self.assertEqual(runtime.get(task["id"])["status"], "awaiting_approval")
        self.assertEqual(len(runtime.pending_approvals(task["id"])), 1)
        with self.assertRaises(PermissionError):
            await runtime.approve(task["id"], "request-1", True, user_id="other")
        self.assertTrue(await runtime.approve(task["id"], "request-1", True))
        self.assertEqual(calls, [("request-1", True, task["id"])])
        self.assertEqual(runtime.pending_approvals(task["id"]), [])
        await self.terminal(runtime, task["id"])
        finish.clear()
        ready.clear()
        another = runtime.create("Delete another")
        await ready.wait()
        await runtime.cancel(another["id"])
        self.assertEqual(runtime.pending_approvals(another["id"]), [])
        self.assertFalse(await runtime.approve(another["id"], "request-1", True))

    async def test_owned_task_access_and_resume_terminal_rejection(self):
        async def runner(task, on_event):
            return {"status": "completed", "response": "Done", "tool_calls": []}
        runtime = self.runtime(runner)
        task = runtime.create("Task", user_id="alice")
        await self.terminal(runtime, task["id"])
        self.assertEqual(runtime.list(user_id="bob"), [])
        with self.assertRaises(PermissionError):
            runtime.events(task["id"], user_id="bob")
        with self.assertRaises(ValueError):
            runtime.resume(task["id"])


class ConversationImportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = DatabaseManager(str(Path(self.directory.name) / "conversations.db"))

    def tearDown(self):
        self.directory.cleanup()

    def test_import_appends_idempotently_and_preserves_metadata(self):
        self.assertTrue(hasattr(self.db, "import_conversation"), "Conversation import must exist")
        record = {"id": "legacy", "title": "Existing chat", "mode": "agent", "metadata": {"custom": "keep"}, "messages": [
            {"id": "user-1", "role": "user", "content": "One", "timestamp": "2026-10-13T00:00:00Z"},
            {"role": "assistant", "content": "Two"},
        ]}
        first = self.db.import_conversation(record, "alice")
        self.db.import_conversation(record, "alice")
        updated = {**record, "messages": [*record["messages"], {"role": "user", "content": "Three"}]}
        imported = self.db.import_conversation(updated, "alice")
        self.assertEqual(len(first["messages"]), 2)
        self.assertEqual([m["content"] for m in imported["messages"]], ["One", "Two", "Three"])
        self.assertEqual(json.loads(imported["metadata_json"]), {"mode": "agent", "custom": "keep"})

    def test_cross_owner_and_invalid_import_leave_existing_records_intact(self):
        self.assertTrue(hasattr(self.db, "import_conversation"), "Conversation import must exist")
        self.db.get_or_create_conversation("chat", "alice", "Keep")
        self.db.add_message("chat", "alice", "user", "Saved")
        with self.assertRaises(PermissionError):
            self.db.import_conversation({"id": "chat", "title": "Changed", "messages": []}, "bob")
        with self.assertRaises(ValueError):
            self.db.import_conversation({"id": "chat", "messages": [{"role": "user", "content": "valid"}, {"role": "bad", "content": "invalid"}]}, "alice")
        self.assertEqual(self.db.list_conversations("alice")[0]["title"], "Keep")
        self.assertEqual(len(self.db.get_messages("chat")), 1)

    def test_round_trip_existing_message_ids_does_not_duplicate_messages(self):
        record = {"id": "chat", "messages": [{"id": "old-1", "role": "user", "content": "Saved", "attachments": ["file.txt"]}]}
        imported = self.db.import_conversation(record, "alice")
        self.db.import_conversation(imported, "alice")
        self.assertEqual(len(self.db.get_messages("chat")), 1)
        self.assertEqual(json.loads(self.db.get_messages("chat")[0]["metadata_json"])["attachments"], ["file.txt"])

    def test_round_trip_live_backend_message_does_not_duplicate(self):
        self.db.get_or_create_conversation("chat", "alice")
        message = self.db.add_message("chat", "alice", "user", "Live message")
        imported = self.db.import_conversation({"id": "chat", "messages": [message]}, "alice")
        self.assertEqual(len(imported["messages"]), 1)

    def test_legacy_messages_without_ids_merge_matching_history_positions(self):
        self.db.get_or_create_conversation("chat", "alice")
        self.db.add_message("chat", "alice", "user", "Repeat")
        imported = self.db.import_conversation({"id": "chat", "messages": [
            {"role": "user", "content": "Repeat"},
            {"role": "user", "content": "Repeat"},
        ]}, "alice")
        self.assertEqual(len(imported["messages"]), 2)
        self.db.import_conversation({"id": "chat", "messages": [
            {"role": "user", "content": "Repeat"},
            {"role": "user", "content": "Repeat"},
        ]}, "alice")
        self.assertEqual(len(self.db.get_messages("chat")), 2)


if __name__ == "__main__":
    unittest.main()
