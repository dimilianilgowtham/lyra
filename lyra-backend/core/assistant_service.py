"""Durable assistant operations exposed through the authenticated local API."""
import asyncio
import json
from datetime import datetime
from zoneinfo import ZoneInfo
import platform

from fastapi import APIRouter, HTTPException
from core.errors import safe_error
from core.task_runtime import TaskRuntime
from core.reminders import ReminderService
from core.tool_registry import ToolDefinition
from core.execution_policy import approved_tool_context

TERMINAL_TOOLS = frozenset({'execute_command', 'read_file', 'write_file', 'list_directory', 'search_files', 'get_current_time'})


class AssistantService:
    def __init__(self, database, ai, executor):
        self.database = database
        self.ai = ai
        self.executor = executor
        self.sockets = {}
        self.runtime = TaskRuntime(database, self.run_task, notify=self.notify, approval_resolver=executor.resolve_approval)
        self.reminders = ReminderService(database, self.deliver_reminder)
        self.router = APIRouter()
        self.register_tools()
        self.register_routes()

    async def deliver_reminder(self, reminder):
        from tools.system_utils import send_notification
        with approved_tool_context(True):
            result = await send_notification(title="Lyra reminder", message=reminder['text'])
        if not result.get('success'):
            raise RuntimeError(result.get('error') or result.get('result') or 'Notification failed')
        return result

    def register_tools(self):
        def add(name, description, properties, required, handler, approval=False):
            self.executor.registry.register(ToolDefinition(name, description,
                {"type": "object", "properties": properties, "required": required}, handler, requires_approval=approval))
        async def remember(fact, category="preference"):
            item = self.database.add_memory('default_user', fact, category, consented=True)
            return {"success": True, "verified": any(m['id'] == item['id'] for m in self.database.get_active_memories('default_user')), "memory": item}
        async def recall(query=""):
            items = self.database.get_active_memories('default_user')
            return {"success": True, "memories": [m for m in items if query.lower() in m['fact'].lower()]}
        async def create_reminder(text, due_at):
            reminder = self.reminders.create(text, due_at)
            return {"success": True, "verified": bool(self.reminders.get(reminder['id'])), "reminder": reminder}
        async def list_reminders():
            return {"success": True, "reminders": self.reminders.list(user_id='default_user')}
        async def cancel_reminder(reminder_id):
            success = self.reminders.cancel(reminder_id, user_id='default_user')
            return {"success": success, "verified": success, "reminder_id": reminder_id}
        async def save_note(title, content):
            note = self.database.add_note('default_user', title, content)
            verified = any(n['id'] == note['id'] for n in self.database.search_notes('default_user', title))
            return {"success": True, "verified": verified, "note": note}
        async def find_notes(query=""):
            return {"success": True, "notes": self.database.search_notes('default_user', query)}
        async def current_time(timezone="Asia/Kolkata"):
            return {"success": True, "time": datetime.now(ZoneInfo(timezone)).isoformat(), "timezone": timezone}
        string = {"type": "string"}
        add('remember_fact', 'Save a personal fact only after explicit consent.', {'fact': string, 'category': string}, ['fact'], remember, True)
        add('recall_memory', 'Retrieve consented personal facts and preferences.', {'query': string}, [], recall)
        add('create_reminder', 'Schedule a local notification at an ISO timestamp with timezone. Obtain current time before converting relative requests.', {'text': string, 'due_at': string}, ['text', 'due_at'], create_reminder, True)
        add('list_reminders', 'List actual saved reminders and delivery states.', {}, [], list_reminders)
        add('cancel_reminder', 'Cancel a saved reminder.', {'reminder_id': string}, ['reminder_id'], cancel_reminder, True)
        add('save_note', 'Save a note in the local database.', {'title': string, 'content': string}, ['title', 'content'], save_note, True)
        add('find_notes', 'Search saved local notes.', {'query': string}, [], find_notes)
        add('get_current_time', 'Read the actual time in an IANA timezone.', {'timezone': string}, [], current_time)

    async def run_task(self, task, on_event):
        async def status(event):
            await on_event(event['type'], {key: value for key, value in event.items() if key != 'type'})
            receipt = event.get('receipt')
            if receipt and event.get('status') in ('completed', 'failed', 'denied', 'cancelled', 'awaiting_approval'):
                arguments = dict(receipt.get('arguments') or {})
                if 'content' in arguments:
                    arguments['content'] = f"[{len(str(arguments['content']))} characters]"
                self.database.log_action(tool=receipt.get('tool', event.get('tool', 'unknown')),
                    arguments=arguments, impact_summary=f"Task {task['id']}: {event['status']}",
                    approved=receipt.get('approved') is True,
                    user_decision='Denied' if receipt.get('denied') else 'Approved' if receipt.get('approved') else 'Not approved',
                    result_summary=safe_error(receipt.get('error') or json.dumps(receipt.get('result', {}), ensure_ascii=False))[:500],
                    duration_ms=receipt.get('duration_ms', 0))
        async def approval(event):
            await on_event('tool_approval_request', {key: value for key, value in event.items() if key != 'type'})
        metadata = task.get('metadata') or {}
        terminal = metadata.get('terminal') is True or task.get('mode') == 'terminal'
        if task.get('tool'):
            receipt = await self.executor.execute_tool(task['tool'], task.get('arguments') or {}, task['id'], on_status=status, on_approval_request=approval, allowed_tools=TERMINAL_TOOLS if terminal else None)
            result = receipt.get('result') or {}
            response = result.get('stdout') or result.get('content') or result.get('result') or receipt.get('error') or json.dumps(result, ensure_ascii=False)
            return {"response": str(response), "status": "completed" if receipt.get('success') else "failed", "tool_calls": [receipt], "iterations": 0}
        instructions = metadata.get('instructions') or metadata.get('context') or ''
        prompt = task['prompt']
        if isinstance(instructions, str) and instructions:
            prompt += '\n\nUser requested response style/context:\n' + instructions[:12000]
        resumed = task.get('resume_context') or {}
        recorded = any(e.get('type') == 'message_recorded' for e in resumed.get('events', []))
        if not recorded:
            await on_event('message_recorded', {'conversation_id': task['conversation_id']})
        result = await self.ai.agentic_chat(prompt, self.executor, task['conversation_id'], task['user_id'],
            on_status=status, on_approval_request=approval, task_id=task['id'],
            model=task.get('model') or '', provider=task.get('provider') or '',
            resume_context=resumed, is_voice=bool(metadata.get('is_voice')), record_user=not recorded,
            terminal_context=metadata if terminal else None)
        return result

    async def notify(self, task, event):
        socket = self.sockets.get(task['id'])
        if not socket:
            return
        payload = event.get('payload') or {}
        message = {'type': event['type'], **payload, 'task_id': task['id'], 'conversation_id': task['conversation_id']}
        if event['type'] == 'agent_response':
            message['text'] = payload.get('response', '')
        try:
            await socket.send_json(message)
            if event['type'] == 'agent_response':
                await socket.send_json({'type': 'state', 'state': 'ready', 'task_id': task['id']})
                self.sockets.pop(task['id'], None)
        except Exception:
            self.sockets.pop(task['id'], None)

    def create_task(self, request):
        prompt = request.get('prompt') or request.get('message') or ''
        tool = request.get('tool')
        if not isinstance(prompt, str) or len(prompt) > 200000 or (not prompt.strip() and not tool):
            raise ValueError('A nonempty prompt of at most 200000 characters is required')
        if tool and (not isinstance(tool, str) or not self.executor.registry.get(tool)):
            raise ValueError('Unknown tool')
        arguments = request.get('arguments') or {}
        metadata = request.get('metadata') or {}
        if isinstance(metadata, dict) and request.get('instructions'):
            if not isinstance(request['instructions'], str):
                raise ValueError('Task instructions must be text')
            metadata = {**metadata, 'instructions': request['instructions']}
        if not isinstance(arguments, dict) or not isinstance(metadata, dict):
            raise ValueError('Tool arguments and task metadata must be objects')
        if metadata.get('terminal') is True or request.get('mode') == 'terminal':
            raw_cwd = metadata.get('cwd') or self.executor.policy.default_root
            if not isinstance(raw_cwd, (str, type(self.executor.policy.default_root))):
                raise ValueError('Working directory must be text')
            directory = self.executor.policy.resolve_path(raw_cwd)
            if not directory.is_dir():
                raise ValueError('Working directory does not exist')
            scope = metadata.get('scope') or ''
            if not isinstance(scope, str) or len(scope) > 4000:
                raise ValueError('Assessment scope must be text of at most 4000 characters')
            if tool and tool not in TERMINAL_TOOLS:
                raise ValueError('This tool is not available in the terminal workspace')
            metadata = {**metadata, 'terminal': True, 'cwd': str(directory), 'scope': scope}
            if tool == 'execute_command' and not arguments.get('cwd'):
                arguments = {**arguments, 'cwd': str(directory)}
        if len(json.dumps(arguments)) > 500000 or len(json.dumps(metadata)) > 20000:
            raise ValueError('Task arguments or context exceed the size limit')
        user_id = request.get('user_id') or 'default_user'
        conv = self.database.get_or_create_conversation(request.get('conversation_id'), user_id=user_id,
            title=(prompt or tool)[:100])
        if conv['user_id'] != user_id:
            raise PermissionError('Conversation belongs to another user')
        return self.runtime.create(prompt or f"Run {tool}", user_id=user_id, conversation_id=conv['id'],
            model=request.get('model') or '', provider=request.get('provider') or '',
            mode=request.get('mode') or 'agent', tool=tool, arguments=arguments, metadata=metadata)

    def register_routes(self):
        router = self.router
        @router.get('/api/terminal/context')
        async def terminal_context():
            return {'cwd': str(self.executor.policy.default_root), 'workspace_roots': [str(path) for path in self.executor.policy.roots], 'platform': platform.system(), 'approval_required': True, 'interactive_stdin': False, 'default_timeout': 30, 'maximum_timeout': 300}
        @router.post('/api/tasks')
        async def create(request: dict):
            return self.create_task(request)
        @router.get('/api/tasks')
        async def list_tasks(user_id: str = 'default_user', limit: int = 50):
            return {'tasks': self.runtime.list(user_id=user_id, limit=min(limit, 200))}
        @router.get('/api/tasks/{task_id}')
        async def task_detail(task_id: str, user_id: str = 'default_user', after_seq: int = 0):
            task = self.runtime.get(task_id, user_id=user_id)
            if not task:
                raise HTTPException(404, 'Task not found')
            return {'task': task, 'events': self.runtime.events(task_id, after_seq=max(0, after_seq), user_id=user_id), 'approvals': self.runtime.pending_approvals(task_id)}
        @router.post('/api/tasks/{task_id}/cancel')
        async def cancel(task_id: str, user_id: str = 'default_user'):
            return await self.runtime.cancel(task_id, user_id=user_id)
        @router.post('/api/tasks/{task_id}/resume')
        async def resume(task_id: str, user_id: str = 'default_user'):
            return self.runtime.resume(task_id, user_id=user_id)
        @router.post('/api/tasks/{task_id}/approvals/{request_id}')
        async def approve(task_id: str, request_id: str, request: dict, user_id: str = 'default_user'):
            if not isinstance(request.get('approved'), bool):
                raise ValueError('approved must be a boolean')
            success = await self.runtime.approve(task_id, request_id, request['approved'], user_id=user_id)
            if not success:
                raise HTTPException(409, 'Approval is no longer pending or belongs to a different task')
            return {'success': True}
        @router.get('/api/reminders')
        async def reminders(user_id: str = 'default_user'):
            return {'reminders': self.reminders.list(user_id=user_id)}
        @router.post('/api/reminders')
        async def add_reminder(request: dict):
            return self.reminders.create(request.get('text'), request.get('due_at'), request.get('user_id') or 'default_user')
        @router.delete('/api/reminders/{reminder_id}')
        async def delete_reminder(reminder_id: str, user_id: str = 'default_user'):
            return {'success': self.reminders.cancel(reminder_id, user_id=user_id)}
        @router.post('/api/conversations/import')
        async def import_conversation(request: dict):
            record = request.get('record') or request
            if not isinstance(record, dict):
                raise ValueError('Conversation record must be an object')
            return self.database.import_conversation(record, request.get('user_id') or 'default_user')
        @router.get('/api/tools')
        async def tools():
            return {'tools': [{'name': item.name, 'description': item.description, 'parameters': item.parameters, 'requires_approval': item.requires_approval} for item in self.executor.registry.list_tools()]}
