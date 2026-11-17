"""Bounded live-provider check using synthetic files and one exact write approval."""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lyra-backend'))


async def verify(folder):
    os.environ['DATABASE_PATH'] = str(folder / 'check.db')
    from core.agent_executor import AgentExecutor
    from core.execution_policy import ExecutionPolicy
    from core.tool_registry import ToolRegistry, ToolDefinition
    from tools.filesystem import read_file, write_file
    source, output = folder / 'input.txt', folder / 'output.txt'
    source.write_text('41')
    registry = ToolRegistry()
    for name, handler, properties, required, approval in [
        ('read_file', read_file, {'filepath': {'type': 'string'}}, ['filepath'], False),
        ('write_file', write_file, {'filepath': {'type': 'string'}, 'content': {'type': 'string'}}, ['filepath', 'content'], True),
    ]:
        registry.register(ToolDefinition(name, name.replace('_', ' '), {'type': 'object', 'properties': properties, 'required': required}, handler, approval))
    executor = AgentExecutor(registry, policy=ExecutionPolicy([folder]), max_tool_calls=5)

    async def approve(event):
        args = event['arguments']
        allowed = event['tool'] == 'write_file' and args.get('filepath') == str(output) and args.get('content', '').strip() == '42'
        executor.resolve_approval(event['request_id'], allowed, 'live-check')

    result = await asyncio.wait_for(executor.run(
        f'Read {source}. Add one to the number. Write only the resulting number to {output}. Read the output back, then report its contents. Use the file tools for each step.',
        [], owner_id='live-check', on_approval_request=approve,
        system_prompt='Complete this synthetic file verification using the tools. Never claim an action without tool evidence.'), timeout=180)
    calls = result.get('tool_calls', [])
    passed = result['status'] == 'completed' and output.exists() and output.read_text().strip() == '42' and sum(c['tool'] == 'read_file' and c['success'] for c in calls) >= 2 and any(c['tool'] == 'write_file' and c['verified'] for c in calls)
    print(json.dumps({'passed': passed, 'status': result['status'], 'provider': result.get('provider'), 'model': result.get('model'), 'receipts': [{'tool': c['tool'], 'success': c['success'], 'verified': c['verified']} for c in calls]}, indent=2))
    return passed


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='lyra-live-check-') as temp:
        sys.exit(0 if asyncio.run(verify(Path(temp))) else 1)
