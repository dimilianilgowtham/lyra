"""Verify a real model -> task -> approval -> local process workflow, without private data."""
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import time

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lyra-backend'))


def verify(folder):
    os.environ['DATABASE_PATH'] = str(folder / 'check.db')
    os.environ['BACKEND_AUTH_TOKEN'] = secrets.token_urlsafe(32)
    os.environ['LYRA_WORKSPACE_ROOTS'] = str(folder)
    from fastapi.testclient import TestClient
    from config import settings
    from core.errors import safe_error
    from main import app
    command = 'printf LYRA_TERMINAL_OK'
    with TestClient(app, headers={'Authorization': f'Bearer {settings.BACKEND_AUTH_TOKEN}'}) as client:
        response = client.post('/api/tasks', json={'prompt': f'Run exactly `{command}` in the terminal, then tell me the output. Do not run any other command.', 'mode': 'terminal', 'metadata': {'cwd': str(folder), 'terminal': True, 'scope': 'Synthetic local command verification'}})
        response.raise_for_status()
        task_id = response.json()['id']
        decisions = set()
        for _ in range(360):
            detail = client.get(f'/api/tasks/{task_id}').json()
            for approval in detail.get('approvals', []):
                if approval['request_id'] in decisions:
                    continue
                decisions.add(approval['request_id'])
                args = approval['arguments']
                exact = approval['tool'] == 'execute_command' and args.get('command') == command and Path(args.get('cwd', '')).resolve() == folder.resolve()
                client.post(f"/api/tasks/{task_id}/approvals/{approval['request_id']}", json={'approved': exact}).raise_for_status()
            task = detail['task']
            if task['status'] in {'completed', 'failed', 'cancelled', 'interrupted'}:
                break
            time.sleep(.5)
        result = task.get('result') or {}
        receipts = result.get('tool_calls', [])
        passed = task['status'] == 'completed' and any(receipt.get('approved') and receipt.get('result', {}).get('stdout') == 'LYRA_TERMINAL_OK' and receipt['result'].get('exit_code') == 0 for receipt in receipts)
        print(json.dumps({'passed': passed, 'status': task['status'], 'provider': result.get('provider'), 'model': result.get('model'), 'error': safe_error(task.get('error') or result.get('response') or '') if not passed else None, 'approvals': len(decisions), 'receipts': [{'tool': receipt['tool'], 'success': receipt['success'], 'exit_code': receipt.get('result', {}).get('exit_code')} for receipt in receipts]}, indent=2))
        return passed


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='lyra-live-terminal-') as temp:
        sys.exit(0 if verify(Path(temp)) else 1)
