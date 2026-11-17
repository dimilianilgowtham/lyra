"""Durable background tasks. Restart recovery never replays a side effect."""
import asyncio
import inspect
import json
import logging
import uuid
from datetime import datetime, timezone

logger = logging.getLogger("LYRA.Tasks")
TERMINAL = {"completed", "failed", "cancelled", "interrupted"}


def _now():
    return datetime.now(timezone.utc).isoformat()


class TaskRuntime:
    """Persist tasks and receipts before delivering optional live notifications.

    Runner signature: ``await runner(task, on_event)``. The runner must return
    an explicit terminal status, and await ``on_event(type, payload)`` for each
    action receipt. notify receives ``(task, event)`` and may be sync or async.
    """
    def __init__(self, database, runner, notify=None, approval_resolver=None):
        self.database = database
        self.runner = runner
        self.notify = notify
        self.approval_resolver = approval_resolver
        self._jobs = {}
        self._closed = False
        conn = self.database._get_connection()
        with conn:
            rows = conn.execute("SELECT id FROM tasks WHERE status IN ('running','awaiting_approval')").fetchall()
            for row in rows:
                self._store_event(row["id"], "task_interrupted", {"reason": "Backend restarted; explicitly resume to continue."}, status="interrupted")
                self._expire_events(row["id"], "Backend restarted")

    @staticmethod
    def _decode(row):
        if row is None:
            return None
        task = dict(row)
        for source, target in (("arguments_json", "arguments"), ("metadata_json", "metadata"), ("result_json", "result"), ("checkpoint_json", "checkpoint")):
            task[target] = json.loads(task.pop(source) or "null")
        return task

    def get(self, task_id, user_id=None):
        task = self._decode(self.database._get_connection().execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())
        if task and user_id is not None and task["user_id"] != user_id:
            raise PermissionError("Task belongs to another user")
        return task

    def _owned(self, task_id, user_id=None):
        task = self.get(task_id, user_id)
        if task is None:
            raise KeyError("Task not found")
        return task

    def list(self, user_id=None, limit=100, status=None):
        clauses, parameters = [], []
        if user_id is not None:
            clauses.append("user_id=?")
            parameters.append(user_id)
        if status is not None:
            clauses.append("status=?")
            parameters.append(status)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        parameters.append(max(1, min(int(limit), 1000)))
        return [self._decode(row) for row in self.database._get_connection().execute("SELECT * FROM tasks" + where + " ORDER BY created_at DESC LIMIT ?", parameters)]

    def events(self, task_id, user_id=None, after_seq=0, limit=1000):
        self._owned(task_id, user_id)
        rows = self.database._get_connection().execute("SELECT * FROM task_events WHERE task_id=? AND seq>? ORDER BY seq LIMIT ?", (task_id, int(after_seq), max(1, min(int(limit), 10000)))).fetchall()
        return [{"task_id": row["task_id"], "seq": row["seq"], "type": row["type"], "payload": json.loads(row["payload_json"]), "created_at": row["created_at"]} for row in rows]

    def _all_events(self, task_id):
        rows = self.database._get_connection().execute("SELECT * FROM task_events WHERE task_id=? ORDER BY seq", (task_id,)).fetchall()
        return [{"task_id": row["task_id"], "seq": row["seq"], "type": row["type"], "payload": json.loads(row["payload_json"]), "created_at": row["created_at"]} for row in rows]

    def pending_approvals(self, task_id, user_id=None):
        self._owned(task_id, user_id)
        pending = {}
        for event in self._all_events(task_id):
            payload = event["payload"]
            if not isinstance(payload, dict):
                continue
            request_id = payload.get("request_id", payload.get("id"))
            if request_id and event["type"] == "tool_approval_request":
                pending[request_id] = payload
            elif request_id and event["type"] in {"tool_approval_resolved", "tool_approval_expired"}:
                pending.pop(request_id, None)
        return list(pending.values())

    def create(self, prompt, user_id="default_user", conversation_id=None, model="", provider="", mode="agent", tool=None, arguments=None, max_steps=None, metadata=None):
        if self._closed:
            raise RuntimeError("Task runtime is stopped")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("Task prompt is required")
        if arguments is not None and not isinstance(arguments, dict):
            raise ValueError("Tool arguments must be an object")
        if conversation_id:
            conv = self.database._get_connection().execute("SELECT user_id FROM conversations WHERE id=?", (conversation_id,)).fetchone()
            if conv and conv["user_id"] != user_id:
                raise PermissionError("Conversation belongs to another user")
        details = dict(metadata or {})
        if max_steps is not None:
            if isinstance(max_steps, bool) or not 1 <= int(max_steps) <= 100:
                raise ValueError("max_steps must be between 1 and 100")
            details["max_steps"] = int(max_steps)
        self.database.get_or_create_user(user_id)
        task_id, now = str(uuid.uuid4()), _now()
        conn = self.database._get_connection()
        with conn:
            conn.execute("INSERT INTO tasks(id,user_id,conversation_id,prompt,status,model,provider,mode,tool,arguments_json,metadata_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (task_id, user_id, conversation_id, prompt.strip(), "queued", model, provider, mode, tool, json.dumps(arguments or {}), json.dumps(details), now, now))
            self._store_event(task_id, "task_status", {"status": "queued"})
        task = self.get(task_id)
        self._schedule(task_id)
        return task

    def _schedule(self, task_id, resumed=False):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # Durable queued task can be explicitly resumed in a loop.
        job = loop.create_task(self._run(task_id, resumed), name=f"lyra-task-{task_id}")
        self._jobs[task_id] = job
        def done(completed):
            if self._jobs.get(task_id) is completed:
                self._jobs.pop(task_id, None)
        job.add_done_callback(done)

    @staticmethod
    def _checkpoint(events):
        completed, partial = [], ""
        for event in events:
            payload = event["payload"]
            if event["type"] == "tool_status" and isinstance(payload, dict):
                receipt = payload.get("receipt") or {}
                if payload.get("status") == "completed" and receipt.get("success", payload.get("success", True)):
                    completed.append(payload)
            elif event["type"] == "token":
                partial += str(payload.get("content", payload.get("text", payload.get("token", "")))) if isinstance(payload, dict) else str(payload)
            elif event["type"] == "agent_response" and isinstance(payload, dict) and payload.get("response"):
                partial = str(payload["response"])
        return {"completed_tool_calls": completed, "partial_response": partial, "last_seq": events[-1]["seq"] if events else 0}

    def _store_event(self, task_id, event_type, payload, status=None):
        conn = self.database._get_connection()
        now = _now()
        with conn:
            # Writing first serializes sequence allocation across connections.
            conn.execute("UPDATE tasks SET updated_at=? WHERE id=?", (now, task_id))
            seq = conn.execute("SELECT COALESCE(MAX(seq),0)+1 FROM task_events WHERE task_id=?", (task_id,)).fetchone()[0]
            conn.execute("INSERT INTO task_events(task_id,seq,type,payload_json,created_at) VALUES(?,?,?,?,?)", (task_id, seq, str(event_type), json.dumps(payload, ensure_ascii=False, default=str), now))
            if status:
                conn.execute("UPDATE tasks SET status=? WHERE id=?", (status, task_id))
            checkpoint = self._checkpoint(self._all_events(task_id))
            conn.execute("UPDATE tasks SET checkpoint_json=? WHERE id=?", (json.dumps(checkpoint), task_id))
        return {"task_id": task_id, "seq": seq, "type": event_type, "payload": payload, "created_at": now}

    async def _emit(self, task_id, event_type, payload):
        task = self._owned(task_id)
        next_status = None
        if task["status"] not in TERMINAL:
            if event_type == "tool_approval_request":
                next_status = "awaiting_approval"
            elif event_type == "tool_status" and isinstance(payload, dict) and payload.get("status") in {"running", "completed", "failed", "denied"} and not self.pending_approvals(task_id):
                next_status = "running"
        event = self._store_event(task_id, event_type, payload, next_status)
        if self.notify:
            try:
                result = self.notify(self.get(task_id), event)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                logger.exception("Task notification failed; persisted event remains available")
        return event

    @staticmethod
    def _failure(result, events):
        if result.get("error"):
            return str(result["error"])
        for call in result.get("tool_calls") or []:
            if isinstance(call, dict) and (call.get("success") is False or call.get("status") in {"failed", "denied"}):
                return str(call.get("error") or "A tool action failed")
        for event in events:
            payload = event["payload"]
            if event["type"] == "tool_status" and isinstance(payload, dict):
                receipt = payload.get("receipt") or {}
                if payload.get("status") in {"failed", "denied"} or (payload.get("status") == "completed" and receipt.get("success") is False):
                    return str(receipt.get("error") or payload.get("error") or "A tool action failed")
        if result.get("status") != "completed":
            return str(result.get("status") or "Runner returned no successful terminal status")
        return ""

    async def _run(self, task_id, resumed):
        task = self._owned(task_id)
        if task["status"] != "queued":
            return
        previous = self._all_events(task_id)
        start_seq = previous[-1]["seq"] if previous else 0
        if resumed:
            task["resume_context"] = {**self._checkpoint(previous), "events": previous[-200:], "resumed": True}
        self._store_event(task_id, "task_status", {"status": "running"}, "running")
        async def on_event(event_type, payload=None):
            if isinstance(event_type, dict):
                record = dict(event_type)
                event_type = record.pop("type")
                payload = record.pop("payload", record)
            return await self._emit(task_id, event_type, payload if payload is not None else {})
        try:
            result = await self.runner(task, on_event)
            if not isinstance(result, dict):
                raise ValueError("Runner must return a result object")
            recent = [event for event in self._all_events(task_id) if event["seq"] > start_seq]
            error = self._failure(result, recent)
            current = self._owned(task_id)
            terminal = current["status"] if current["status"] in {"cancelled", "interrupted"} else ("cancelled" if result.get("status") == "cancelled" else "failed" if error else "completed")
            result = dict(result)
            if result.get("status") != terminal:
                result["runner_status"] = result.get("status")
            result["status"] = terminal
            if error:
                result["error"] = error
            with self.database._get_connection() as conn:
                conn.execute("UPDATE tasks SET result_json=?, error=?, updated_at=? WHERE id=?", (json.dumps(result, default=str), error, _now(), task_id))
            self._store_event(task_id, "task_status", {"status": terminal, "error": error}, terminal)
            await self._emit(task_id, "agent_response", result)
            self._expire_events(task_id, "Task ended")
        except asyncio.CancelledError:
            current = self._owned(task_id)
            if current["status"] not in {"cancelled", "interrupted"}:
                self._store_event(task_id, "task_status", {"status": "interrupted"}, "interrupted")
            self._expire_events(task_id, "Task stopped")
            raise
        except Exception as exc:
            logger.exception("Task runner failed")
            current = self._owned(task_id)
            terminal = current["status"] if current["status"] in {"cancelled", "interrupted"} else "failed"
            with self.database._get_connection() as conn:
                conn.execute("UPDATE tasks SET error=? WHERE id=?", (str(exc), task_id))
            await self._emit(task_id, "agent_response", {"status": terminal, "error": str(exc), "response": ""})
            self._store_event(task_id, "task_status", {"status": terminal, "error": str(exc)}, terminal)
            self._expire_events(task_id, "Task failed")

    def _expire_events(self, task_id, reason):
        pending = self.pending_approvals(task_id)
        for approval in pending:
            self._store_event(task_id, "tool_approval_expired", {"request_id": approval.get("request_id", approval.get("id")), "reason": reason})
        return pending

    async def approve(self, task_id, request_id, approved, user_id=None):
        task = self._owned(task_id, user_id)
        if task["status"] != "awaiting_approval" or not any(a.get("request_id", a.get("id")) == request_id for a in self.pending_approvals(task_id)):
            return False
        if not self.approval_resolver:
            return False
        resolved = self.approval_resolver(request_id, bool(approved), owner_id=task_id)
        if inspect.isawaitable(resolved):
            resolved = await resolved
        if resolved is False:
            return False
        await self._emit(task_id, "tool_approval_resolved", {"request_id": request_id, "approved": bool(approved)})
        if self.get(task_id)["status"] == "awaiting_approval" and not self.pending_approvals(task_id):
            self._store_event(task_id, "task_status", {"status": "running"}, "running")
        return True

    async def cancel(self, task_id, user_id=None):
        task = self._owned(task_id, user_id)
        if task["status"] in TERMINAL:
            return task
        self._store_event(task_id, "task_status", {"status": "cancelled"}, "cancelled")
        job = self._jobs.get(task_id)
        if job:
            job.cancel()
        expired = self._expire_events(task_id, "Task cancelled")
        if self.approval_resolver:
            for approval in expired:
                resolved = self.approval_resolver(approval.get("request_id", approval.get("id")), False, owner_id=task_id)
                if inspect.isawaitable(resolved):
                    await resolved
        if job:
            await self._settle(job)
        await self._emit(task_id, "task_status", {"status": "cancelled"})
        return self.get(task_id)

    def resume(self, task_id, user_id=None):
        if self._closed:
            raise RuntimeError("Task runtime is stopped")
        task = self._owned(task_id, user_id)
        if task["status"] not in {"interrupted", "failed", "cancelled", "queued"} or task_id in self._jobs:
            raise ValueError("Only an inactive interrupted, failed, cancelled or queued task can resume")
        self._expire_events(task_id, "Task resumed; fresh approval required")
        with self.database._get_connection() as conn:
            conn.execute("UPDATE tasks SET error='' WHERE id=?", (task_id,))
        self._store_event(task_id, "task_resumed", {"previous_status": task["status"]}, "queued")
        resumed = self.get(task_id)
        self._schedule(task_id, resumed=True)
        return resumed

    @staticmethod
    async def _settle(job):
        try:
            await asyncio.wait_for(asyncio.shield(job), timeout=2)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass

    async def shutdown(self):
        self._closed = True
        jobs = list(self._jobs.items())
        for task_id, job in jobs:
            if not job.done() and self.get(task_id)["status"] not in TERMINAL:
                self._store_event(task_id, "task_interrupted", {"reason": "Backend stopped; explicitly resume to continue."}, "interrupted")
                self._expire_events(task_id, "Backend stopped")
            job.cancel()
        if jobs:
            await asyncio.gather(*(self._settle(job) for _, job in jobs))
