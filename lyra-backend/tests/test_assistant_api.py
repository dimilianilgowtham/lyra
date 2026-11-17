"""Exercise real task approvals and file results through the authenticated API."""
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fastapi.testclient import TestClient
from main import app, agent_executor
from config import settings
from core.database import db
from core.execution_policy import ExecutionPolicy


class AssistantAPITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.policy = patch.object(agent_executor, 'policy', ExecutionPolicy([self.temp.name]))
        self.policy.start()
        self.client = TestClient(app, headers={'Authorization': f'Bearer {settings.BACKEND_AUTH_TOKEN}'})
        self.client.__enter__()
    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.policy.stop()
        self.temp.cleanup()
    def wait(self, task_id, statuses):
        for _ in range(200):
            response = self.client.get(f'/api/tasks/{task_id}')
            self.assertEqual(response.status_code, 200, response.text)
            detail = response.json()
            if detail['task']['status'] in statuses:
                return detail
            time.sleep(.01)
        self.fail('Task did not reach the expected state')
    def write_task(self, path):
        response = self.client.post('/api/tasks', json={'prompt': 'Write integration note', 'tool': 'write_file', 'arguments': {'filepath': str(path), 'content': 'Verified API output'}})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['id']
    def test_write_requires_approval_then_records_real_verified_output(self):
        path = Path(self.temp.name) / 'approved.txt'
        task_id = self.write_task(path)
        detail = self.wait(task_id, {'awaiting_approval'})
        self.assertFalse(path.exists())
        approval = detail['approvals'][0]['request_id']
        accepted = self.client.post(f'/api/tasks/{task_id}/approvals/{approval}', json={'approved': True})
        self.assertEqual(accepted.status_code, 200, accepted.text)
        result = self.wait(task_id, {'completed', 'failed'})['task']
        self.assertEqual(result['status'], 'completed', result)
        self.assertEqual(path.read_text(), 'Verified API output')
        self.assertTrue(result['result']['tool_calls'][0]['verified'])
        self.assertTrue(any(log['tool'] == 'write_file' and str(path) in str(log) for log in db.get_audit_log(100)))
    def test_denial_does_not_write_or_appear_approved(self):
        path = Path(self.temp.name) / 'denied.txt'
        task_id = self.write_task(path)
        approval = self.wait(task_id, {'awaiting_approval'})['approvals'][0]['request_id']
        self.client.post(f'/api/tasks/{task_id}/approvals/{approval}', json={'approved': False})
        result = self.wait(task_id, {'failed'})['task']['result']
        self.assertFalse(path.exists())
        self.assertFalse(result['tool_calls'][0]['approved'])
        self.assertTrue(result['tool_calls'][0]['denied'])
    def test_saved_conversation_keeps_the_requested_id(self):
        requested = f'api-import-{uuid.uuid4()}'
        response = self.client.post('/api/conversations', json={'record': {'id': requested, 'title': 'Actual saved chat', 'messages': [{'role': 'user', 'content': 'Keep this context'}]}})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['id'], requested)
        self.assertEqual(self.client.get(f'/api/conversations/{requested}/messages').json()['messages'][0]['content'], 'Keep this context')

    def test_terminal_chat_uses_cwd_and_approval_before_command(self):
        from unittest.mock import AsyncMock
        model = AsyncMock(side_effect=[{'tool_calls': [{'name': 'execute_command', 'arguments': {'command': 'pwd'}}]}, {'content': 'Printed the working directory.'}])
        with patch.object(agent_executor, 'model_caller', model):
            response = self.client.post('/api/tasks', json={'mode': 'terminal', 'prompt': 'Print the working directory', 'metadata': {'terminal': True, 'cwd': self.temp.name, 'scope': 'Local integration test'}})
            self.assertEqual(response.status_code, 200, response.text)
            task_id = response.json()['id']
            detail = self.wait(task_id, {'awaiting_approval'})
            approval = detail['approvals'][0]
            self.assertEqual(Path(approval['arguments']['cwd']).resolve(), Path(self.temp.name).resolve())
            self.client.post(f"/api/tasks/{task_id}/approvals/{approval['request_id']}", json={'approved': True})
            task = self.wait(task_id, {'completed', 'failed'})['task']
            self.assertEqual(task['status'], 'completed', task)
            self.assertEqual(Path(task['result']['tool_calls'][0]['result']['stdout'].strip()).resolve(), Path(self.temp.name).resolve())

    def test_terminal_rejects_bad_working_directory_before_creating_task(self):
        response = self.client.post('/api/tasks', json={'mode': 'terminal', 'prompt': 'Inspect the directory', 'metadata': {'terminal': True, 'cwd': '/etc'}})
        self.assertEqual(response.status_code, 400, response.text)


if __name__ == '__main__': unittest.main()
