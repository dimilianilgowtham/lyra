"""Conversation and agent context must come from real saved records."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.ai_orchestrator import AIOrchestrator
from core.database import DatabaseManager


class Adapter:
    name = "groq"
    DEFAULT_MODEL = "default-model"
    def __init__(self, fail=False):
        self.fail = fail
        self.requests = []
    async def chat(self, **request):
        self.requests.append(request)
        if self.fail:
            raise RuntimeError("Provider unavailable")
        return "A real provider response"


class Registry:
    def __init__(self, adapter): self.adapter = adapter
    def get_fallback_order(self, preferred_provider=""): return [self.adapter]
    def resolve_adapter(self, model="", preferred_provider=""): return self.adapter


class TestAIContext(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.database = DatabaseManager(str(Path(self.directory.name) / "context.db"))
        self.ai = AIOrchestrator()
        self.ai.db = self.database
    def tearDown(self): self.directory.cleanup()

    async def test_long_conversation_keeps_latest_messages_in_order(self):
        conv = self.database.get_or_create_conversation(None)
        for index in range(45):
            self.database.add_message(conv['id'], 'default_user', 'user', f'turn {index}')
        recent = self.database.get_messages(conv['id'], limit=40)
        self.assertEqual(recent[0]['content'], 'turn 5')
        self.assertEqual(recent[-1]['content'], 'turn 44')

    async def test_terminal_followup_contains_owned_saved_output(self):
        import json
        conv = self.database.get_or_create_conversation(None)
        connection = self.database._get_connection()
        evidence = {'tool_calls': [{'tool': 'execute_command', 'arguments': {'command': 'printf evidence'}, 'success': True, 'result': {'stdout': 'actual saved diagnostic', 'stderr': 'warning details', 'exit_code': 0}}]}
        with connection:
            connection.execute("INSERT INTO tasks(id,user_id,conversation_id,prompt,status,result_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)", ('previous-terminal', 'default_user', conv['id'], 'Read diagnostic', 'completed', json.dumps(evidence), '2026-01-01', '2026-01-01'))
        class Executor:
            async def run(self, **request):
                self.request = request
                return {'response': 'Analysis', 'status': 'completed', 'tool_calls': []}
        executor = Executor()
        await self.ai.agentic_chat('Explain the previous output', executor, conv['id'], task_id='followup', terminal_context={'cwd': self.directory.name})
        self.assertIn('actual saved diagnostic', executor.request['system_prompt'])
        self.assertIn('warning details', executor.request['system_prompt'])
        self.assertIn('exit_code', executor.request['system_prompt'])

    async def test_inferred_provider_keeps_requested_model(self):
        adapter = Adapter()
        from unittest.mock import patch
        with patch("core.ai_orchestrator.model_registry", Registry(adapter)):
            result = await self.ai.chat("Hello", model="selected-model")
        self.assertEqual(adapter.requests[0]["model"], "selected-model")
        self.assertEqual(result["model"], "selected-model")
        self.assertEqual(result["status"], "completed")

    async def test_provider_failure_is_a_failed_result(self):
        from unittest.mock import patch
        with patch("core.ai_orchestrator.model_registry", Registry(Adapter(fail=True))):
            result = await self.ai.chat("Hello")
        self.assertEqual(result["status"], "failed")
        self.assertIsNone(result["provider"])

    async def test_prompt_uses_actual_user_and_consented_memories(self):
        self.database.get_or_create_user("sarah", name="Sarah")
        self.database.add_memory("sarah", "Uses Python", consented=True)
        self.database.add_memory("sarah", "Unconsented private fact", consented=False)
        prompt = self.ai._build_augmented_system_prompt("sarah")
        self.assertIn("Sarah", prompt)
        self.assertIn("Uses Python", prompt)
        self.assertNotIn("Anil Gowtham", prompt)
        self.assertNotIn("Unconsented private fact", prompt)

    async def test_agent_receives_saved_context_and_task_ownership(self):
        self.database.add_memory("default_user", "Prefers concise responses", consented=True)
        conv = self.database.get_or_create_conversation(None)
        self.database.add_message(conv["id"], "default_user", "user", "Project uses Rust")
        class Executor:
            async def run(self, **request):
                self.request = request
                return {"response": "Inspected project", "status": "completed", "tool_calls": []}
        executor = Executor()
        await self.ai.agentic_chat("Inspect it", executor, conv["id"], task_id="task-123")
        self.assertIn("Prefers concise", executor.request["system_prompt"])
        self.assertEqual(executor.request["task_id"], "task-123")
        self.assertIn("Project uses Rust", executor.request["conversation_history"][0]["content"])


if __name__ == "__main__": unittest.main()
