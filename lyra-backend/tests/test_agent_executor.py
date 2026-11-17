import asyncio
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.agent_executor import AgentExecutor
from core.tool_registry import ToolDefinition, ToolRegistry


class AgentExecutionTests(unittest.IsolatedAsyncioTestCase):
    def registry(self, handler, name="change", approval=True):
        registry = ToolRegistry()
        registry.register(ToolDefinition(name, "test tool", {"type": "object", "properties": {}, "required": []}, handler, approval))
        return registry

    async def test_no_callback_never_executes_mutation(self):
        executed = []
        async def change():
            executed.append(True)
            return {"success": True}
        agent = AgentExecutor(self.registry(change))
        self.assertTrue(hasattr(agent, "execute_tool"), "manual and agent actions need one approval gate")
        result = await agent.execute_tool("change", {}, "owner")
        self.assertEqual(result["status"], "awaiting_approval")
        self.assertFalse(result["success"])
        self.assertEqual(executed, [])
        self.assertEqual(agent.pending_approvals, {})

    async def test_approval_belongs_to_owner_and_denial_is_receipted(self):
        async def change():
            self.fail("denied action executed")
        agent = AgentExecutor(self.registry(change))
        self.assertTrue(hasattr(agent, "execute_tool"))
        async def approve(event):
            self.assertEqual(event["owner_id"], "owner")
            self.assertFalse(agent.resolve_approval(event["request_id"], True, "intruder"))
            self.assertTrue(agent.resolve_approval(event["request_id"], False, "owner"))
        receipt = await agent.execute_tool("change", {}, "owner", on_approval_request=approve)
        self.assertEqual(receipt["status"], "denied")
        self.assertTrue(receipt["denied"])
        self.assertFalse(receipt["approved"])

    async def test_cancel_removes_approval_and_propagates(self):
        ready = asyncio.Event()
        async def change():
            self.fail("cancelled action executed")
        async def approval(event):
            ready.set()
        agent = AgentExecutor(self.registry(change))
        self.assertTrue(hasattr(agent, "execute_tool"))
        task = asyncio.create_task(agent.execute_tool("change", {}, "owner", on_approval_request=approval))
        await ready.wait()
        request_id = next(iter(agent.pending_approvals))
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(agent.pending_approvals, {})
        self.assertFalse(agent.resolve_approval(request_id, True, "owner"))

    async def test_handler_failure_is_failed_and_full_result_retained(self):
        async def failing():
            return {"success": False, "error": "disk full", "details": {"free": 0}}
        statuses = []
        async def status(event):
            statuses.append(event)
        agent = AgentExecutor(self.registry(failing, "inspect", False))
        self.assertTrue(hasattr(agent, "execute_tool"))
        receipt = await agent.execute_tool("inspect", {}, "owner", on_status=status)
        self.assertEqual(receipt["status"], "failed")
        self.assertEqual(receipt["result"]["details"], {"free": 0})
        self.assertEqual(statuses[-1]["status"], "failed")

    async def test_invalid_arguments_do_not_reach_handler(self):
        async def inspect():
            self.fail("invalid arguments reached handler")
        agent = AgentExecutor(self.registry(inspect, "inspect", False))
        self.assertTrue(hasattr(agent, "execute_tool"))
        receipt = await agent.execute_tool("inspect", {"unexpected": 1}, "owner")
        self.assertEqual(receipt["status"], "failed")
        self.assertIn("unexpected", receipt["error"])

    async def test_multiple_calls_and_full_results_are_sent_back(self):
        async def inspect():
            return {"success": True, "content": "full " + "evidence " * 100}
        turns = []
        async def model_caller(messages, tools, **kwargs):
            turns.append(json.loads(json.dumps(messages)))
            if len(turns) == 1:
                return {"content": "", "tool_calls": [{"id": "one", "name": "inspect", "arguments": {}}, {"id": "two", "name": "inspect", "arguments": {}}], "provider": "test", "model": "test-model"}
            return {"content": "Read two files.", "tool_calls": [], "provider": "test", "model": "test-model"}
        agent = AgentExecutor(self.registry(inspect, "inspect", False), model_caller=model_caller)
        result = await agent.run("inspect twice", [], owner_id="owner", system_prompt="Personal memory: tea")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(result["tool_calls"]), 2)
        tools = [m for m in turns[1] if m["role"] == "tool"]
        self.assertEqual([m["tool_call_id"] for m in tools], ["one", "two"])
        self.assertIn("evidence " * 100, json.loads(tools[0]["content"])["result"]["content"])
        self.assertIn("Personal memory: tea", turns[0][0]["content"])

    async def test_budget_reports_actual_successful_steps(self):
        async def inspect():
            return {"success": True, "path": "/approved/read.txt"}
        async def caller(messages, tools, **kwargs):
            return {"tool_calls": [{"id": "one", "name": "inspect", "arguments": {}}]}
        agent = AgentExecutor(self.registry(inspect, "inspect", False), model_caller=caller, max_tool_calls=1)
        result = await agent.run("inspect", [])
        self.assertEqual(result["status"], "budget_exhausted")
        self.assertIn("inspect", result["response"])
        self.assertIn("1", result["response"])

    async def test_real_http_protocol_works_without_gemini_and_fails_over(self):
        import httpx
        from core.tool_model import ToolModelCaller
        requests = []
        def respond(request):
            requests.append(request)
            if "groq.com" in str(request.url):
                return httpx.Response(429, json={"error": {"message": "limited"}})
            return httpx.Response(200, json={"choices": [{"message": {"content": "Available", "tool_calls": []}}]})
        settings = SimpleNamespace(GROQ_API_KEY="test-groq", OPENAI_API_KEY="test-openai", OPENROUTER_API_KEY="", NVIDIA_API_KEY="", GEMINI_API_KEY="", OLLAMA_BASE_URL="http://localhost:11434", DEFAULT_LOCAL_MODEL="llama3.2")
        caller = ToolModelCaller(settings_obj=settings, transport=httpx.MockTransport(respond))
        agent = AgentExecutor(ToolRegistry(), model_caller=caller)
        result = await agent.run("hello", [], provider="groq")
        self.assertEqual(result["provider"], "openai")
        self.assertEqual(result["response"], "Available")
        self.assertEqual(len(requests), 2)
        self.assertIn("messages", json.loads(requests[-1].content))

    async def test_provider_protocols_preserve_multiple_tool_call_ids(self):
        import httpx
        from core.tool_model import ToolModelCaller
        for provider in ["groq", "openai", "openrouter", "nvidia", "ollama"]:
            with self.subTest(provider=provider):
                requests = []
                def respond(request):
                    requests.append(request)
                    return httpx.Response(200, json={"choices": [{"message": {"content": None, "tool_calls": [{"id": "read-1", "type": "function", "function": {"name": "inspect", "arguments": "{}"}}, {"id": "read-2", "type": "function", "function": {"name": "inspect", "arguments": "{}"}}]}}]})
                settings = SimpleNamespace(GROQ_API_KEY="fake", OPENAI_API_KEY="fake", OPENROUTER_API_KEY="fake", NVIDIA_API_KEY="fake", GEMINI_API_KEY="", OLLAMA_BASE_URL="http://localhost:11434", DEFAULT_LOCAL_MODEL="llama3.2")
                caller = ToolModelCaller(settings_obj=settings, transport=httpx.MockTransport(respond))
                turn = await caller([{"role": "system", "content": "test"}, {"role": "user", "content": "inspect"}], [], provider=provider)
                self.assertEqual(turn["provider"], provider)
                self.assertEqual([call["id"] for call in turn["tool_calls"]], ["read-1", "read-2"])

    async def test_approval_timeout_expires_request(self):
        requests = []
        async def change():
            self.fail("expired approval executed")
        async def approval(event):
            requests.append(event)
        agent = AgentExecutor(self.registry(change), approval_timeout=0.01)
        receipt = await agent.execute_tool("change", {}, "owner", on_approval_request=approval)
        self.assertEqual(receipt["status"], "denied")
        self.assertIn("expired", receipt["error"])
        self.assertFalse(agent.resolve_approval(requests[0]["request_id"], True, "owner"))

    async def test_approval_executes_the_original_arguments(self):
        executed = []
        async def change(value):
            executed.append(value)
            return {"success": True}
        registry = ToolRegistry()
        registry.register(ToolDefinition("change", "change", {"type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"]}, change, True))
        agent = AgentExecutor(registry)
        arguments = {"value": "approved"}
        async def approve(event):
            arguments["value"] = "changed after prompt"
            agent.resolve_approval(event["request_id"], True, "owner")
        receipt = await agent.execute_tool("change", arguments, "owner", on_approval_request=approve)
        self.assertTrue(receipt["success"])
        self.assertEqual(executed, ["approved"])


if __name__ == "__main__":
    unittest.main()
