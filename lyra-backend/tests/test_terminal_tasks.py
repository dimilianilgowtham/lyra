"""Terminal instructions exercise real processes behind the task approval gate."""
import asyncio
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import settings
from core.agent_executor import AgentExecutor
from core.execution_policy import ExecutionPolicy, approved_tool_context
from core.tool_registry import build_default_registry
from tools.shell import execute_command


class TerminalExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_terminal_turn_uses_selected_directory_and_limited_tools(self):
        with tempfile.TemporaryDirectory() as temp:
            calls, events = [], []
            async def model(messages, tools, **kwargs):
                calls.append(tools)
                if len(calls) == 1:
                    return {'tool_calls': [{'name': 'execute_command', 'arguments': {'command': 'pwd'}}]}
                return {'content': 'The selected working directory was printed.'}
            executor = AgentExecutor(build_default_registry(), policy=ExecutionPolicy([temp]), model_caller=model)
            async def approve(event):
                self.assertEqual(Path(event['arguments']['cwd']).resolve(), Path(temp).resolve())
                executor.resolve_approval(event['request_id'], True, 'terminal-test')
            async def status(event): events.append(event)
            result = await executor.run('Print my working directory', [], owner_id='terminal-test',
                default_cwd=temp, allowed_tools={'execute_command'}, on_status=status, on_approval_request=approve)
            self.assertEqual(result['status'], 'completed', result)
            self.assertEqual([tool['function']['name'] for tool in calls[0]], ['execute_command'])
            receipt = result['tool_calls'][0]
            self.assertEqual(Path(receipt['result']['stdout'].strip()).resolve(), Path(temp).resolve())
            self.assertEqual(receipt['result']['cwd'], str(Path(temp).resolve()))
            self.assertEqual(receipt['result']['exit_code'], 0)
            self.assertTrue(any(event['status'] == 'awaiting_approval' for event in events))

    async def test_a_model_cannot_call_a_tool_outside_terminal_toolset(self):
        ran = []
        registry = build_default_registry()
        async def forbidden(): ran.append(True); return {'success': True}
        registry.get('get_clipboard').handler = forbidden
        async def model(messages, tools, **kwargs):
            if not any(message['role'] == 'tool' for message in messages):
                return {'tool_calls': [{'name': 'get_clipboard', 'arguments': {}}]}
            return {'content': 'The tool was unavailable.'}
        executor = AgentExecutor(registry, model_caller=model)
        result = await executor.run('Inspect the terminal', [], allowed_tools={'execute_command'})
        self.assertEqual(ran, [])
        self.assertEqual(result['status'], 'failed')
        self.assertIn('not available', result['tool_calls'][0]['error'])

    async def test_shell_has_receipts_and_does_not_inherit_provider_credentials(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'GROQ_API_KEY': 'synthetic-do-not-inherit'}):
            with approved_tool_context(True, policy=ExecutionPolicy([temp])):
                result = await execute_command('printf "%s" "${GROQ_API_KEY:-clean}"; printf diagnostic >&2; exit 7', temp)
            self.assertEqual(result['stdout'], 'clean')
            self.assertEqual(result['stderr'], 'diagnostic')
            self.assertEqual(result['exit_code'], 7)
            self.assertEqual(result['cwd'], str(Path(temp).resolve()))
            self.assertGreaterEqual(result['duration_ms'], 0)
            self.assertFalse(result['success'])

    async def test_timeout_retains_partial_output(self):
        with tempfile.TemporaryDirectory() as temp:
            with approved_tool_context(True, policy=ExecutionPolicy([temp])):
                result = await execute_command('printf started; sleep 5', temp, timeout=.1)
            self.assertFalse(result['success'])
            self.assertEqual(result['stdout'], 'started')
            self.assertTrue(result['timed_out'])


if __name__ == '__main__': unittest.main()
