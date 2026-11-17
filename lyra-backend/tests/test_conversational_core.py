"""
Unit Tests for LYRA Conversational Core:
SQLite database persistence, multi-turn history, memory consent, and model adapters.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from core.database import DatabaseManager
from core.model_adapter import ModelAdapterRegistry, BaseModelAdapter


class MockAdapter(BaseModelAdapter):
    name: str = "mock"

    def is_available(self) -> bool:
        return True

    async def chat(self, messages, system_prompt, model, temperature, max_tokens):
        return f"Mock reply to {len(messages)} messages (temp={temperature}, max_tokens={max_tokens}, model={model})"

    async def stream_chat(self, messages, system_prompt, model, temperature, max_tokens):
        yield "Mock "
        yield "stream"


class TestConversationalCore(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_lyra.db"
        self.db = DatabaseManager(str(self.db_path))

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_user_and_conversation_persistence(self):
        """Verify user and conversation creation and multi-turn message storage."""
        user = self.db.get_or_create_user("user_123", name="Anil")
        self.assertEqual(user["id"], "user_123")
        self.assertEqual(user["name"], "Anil")

        conv = self.db.get_or_create_conversation(None, user_id="user_123", title="Test Conversation")
        conv_id = conv["id"]
        self.assertEqual(conv["title"], "Test Conversation")

        # Turn 1
        msg1 = self.db.add_message(conv_id, "user_123", "user", "Hello Lyra", model="test-model")
        msg2 = self.db.add_message(conv_id, "user_123", "assistant", "Hello Anil! How can I assist you?", model="test-model")

        # Turn 2
        msg3 = self.db.add_message(conv_id, "user_123", "user", "What is my name?")
        msg4 = self.db.add_message(conv_id, "user_123", "assistant", "Your name is Anil.")

        messages = self.db.get_messages(conv_id)
        self.assertEqual(len(messages), 4)
        self.assertEqual(messages[0]["content"], "Hello Lyra")
        self.assertEqual(messages[2]["content"], "What is my name?")
        self.assertEqual(messages[3]["content"], "Your name is Anil.")

    def test_consented_personal_memories(self):
        """Verify memory storage, consent toggling, and forgetting."""
        user_id = "user_456"
        
        # Add memory
        mem1 = self.db.add_memory(user_id, "Prefers Python over JavaScript", category="preference", consented=True)
        mem2 = self.db.add_memory(user_id, "Works on macOS Air", category="fact", consented=True)
        mem_id = mem1["id"]

        active = self.db.get_active_memories(user_id)
        self.assertEqual(len(active), 2)

        # Toggle consent off
        self.db.update_memory(mem_id, consented=False)
        active_after = self.db.get_active_memories(user_id)
        self.assertEqual(len(active_after), 1)
        self.assertEqual(active_after[0]["fact"], "Works on macOS Air")

        # Delete/Forget memory
        self.db.delete_memory(mem2["id"])
        remaining = self.db.get_active_memories(user_id)
        self.assertEqual(len(remaining), 0)

    def test_action_audit_log(self):
        """Verify tool action logging for safety and compliance."""
        audit_id = self.db.log_action(
            tool="execute_command",
            arguments={"command": "git status"},
            impact_summary="Read-only query of git working tree",
            approved=True,
            user_decision="User clicked Approve",
            result_summary="On branch main",
            duration_ms=45.2,
        )
        self.assertIsNotNone(audit_id)

        logs = self.db.get_audit_log(limit=10)
        self.assertTrue(len(logs) >= 1)
        self.assertEqual(logs[0]["tool"], "execute_command")
        self.assertEqual(logs[0]["approved"], 1)

    async def test_model_adapter_registry(self):
        """Verify model adapter registry and parameter passing."""
        registry = ModelAdapterRegistry()
        mock_adapter = MockAdapter()
        registry.adapters["mock"] = mock_adapter

        resolved = registry.resolve_adapter(preferred_provider="mock")
        self.assertEqual(resolved.name, "mock")

        res = await resolved.chat(
            messages=[{"role": "user", "content": "Hi"}],
            system_prompt="You are Lyra.",
            model="custom-v1",
            temperature=0.8,
            max_tokens=420,
        )
        self.assertIn("temp=0.8", res)
        self.assertIn("max_tokens=420", res)
        self.assertIn("model=custom-v1", res)

    async def test_tool_registry_and_intent_routing(self):
        """Verify that ToolRegistry registers all native macOS tools and IntentRouter routes correctly."""
        from core.tool_registry import build_default_registry
        from core.intent_router import IntentRouter

        registry = build_default_registry()
        expected_tools = [
            "execute_command", "read_file", "write_file", "list_directory",
            "search_files", "take_screenshot", "open_app", "close_app",
            "set_volume", "mute_volume", "unmute_volume", "open_url",
            "create_folder", "get_active_window", "toggle_dark_mode",
            "get_system_stats", "web_search", "get_clipboard", "set_clipboard",
            "send_notification", "get_wifi_info", "get_battery_info",
        ]
        for tool_name in expected_tools:
            self.assertIsNotNone(registry.get(tool_name), f"Expected tool {tool_name} to be registered")

        # Test IntentRouter routing
        status_route = await IntentRouter.route("system status")
        self.assertEqual(status_route["category"], "system")
        self.assertIn("CPU is at", status_route["speak"])

        agent_route = await IntentRouter.route("create a file named test.py with hello world")
        self.assertEqual(agent_route["category"], "agent")


if __name__ == "__main__":
    unittest.main()
