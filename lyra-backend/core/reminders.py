"""Persistent local reminders with atomic claims and conservative retries."""
import asyncio
import inspect
import logging
import uuid
from datetime import datetime, timezone

logger = logging.getLogger("LYRA.Reminders")


class RetryableDeliveryError(Exception):
    """Delivery definitely did not happen; the service may safely retry."""


def _aware(value):
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError) as exc:
        raise ValueError("due_at must be an ISO timestamp with a timezone") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("due_at must include a timezone")
    return parsed


class ReminderService:
    """Deliver due reminders using ``await deliver(reminder)``.

    None/True or a result with success=True confirms delivery. An exception or
    False records failure without automatic replay, because delivery could have
    occurred before acknowledgment. RetryableDeliveryError is reserved for
    failures known to have happened before delivery and gets three attempts.
    """
    def __init__(self, database, deliver, clock=None, poll_interval=1, max_attempts=3):
        self.database = database
        self.deliver = deliver
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.poll_interval = max(.01, float(poll_interval))
        self.max_attempts = max(1, int(max_attempts))
        self._job = None
        conn = self.database._get_connection()
        now = self._now().isoformat()
        with conn:
            # A claim has not called the notifier yet. Delivering is ambiguous
            # after a crash and must not generate duplicate notifications.
            conn.execute("UPDATE reminders SET status='pending', claimed_at=NULL, updated_at=? WHERE status='claimed'", (now,))
            conn.execute("UPDATE reminders SET status='failed', error=?, updated_at=? WHERE status='delivering'", ("Delivery was interrupted; its outcome is unknown. No automatic retry.", now))

    def _now(self):
        return _aware(self.clock())

    def create(self, text, due_at, user_id="default_user"):
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Reminder text is required")
        if len(text.strip()) > 5000:
            raise ValueError("Reminder text must be at most 5000 characters")
        due = _aware(due_at)
        self.database.get_or_create_user(user_id)
        now, reminder_id = self._now().isoformat(), str(uuid.uuid4())
        with self.database._get_connection() as conn:
            conn.execute("INSERT INTO reminders(id,user_id,text,due_at,due_timestamp,status,next_attempt_at,created_at,updated_at) VALUES(?,?,?,?,?,'pending',?,?,?)", (reminder_id, user_id, text.strip(), due.isoformat(), due.timestamp(), due.timestamp(), now, now))
        return self.get(reminder_id)

    def get(self, reminder_id, user_id=None):
        row = self.database._get_connection().execute("SELECT * FROM reminders WHERE id=?", (reminder_id,)).fetchone()
        if not row:
            return None
        if user_id is not None and row["user_id"] != user_id:
            raise PermissionError("Reminder belongs to another user")
        return dict(row)

    def list(self, user_id=None, upcoming=False, limit=100, status=None):
        clauses, parameters = [], []
        if user_id is not None:
            clauses.append("user_id=?")
            parameters.append(user_id)
        if upcoming:
            clauses.append("status IN ('pending','claimed','delivering')")
        if status is not None:
            clauses.append("status=?")
            parameters.append(status)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        parameters.append(max(1, min(int(limit), 1000)))
        return [dict(row) for row in self.database._get_connection().execute("SELECT * FROM reminders" + where + " ORDER BY due_timestamp ASC, created_at ASC LIMIT ?", parameters)]

    def list_upcoming(self, user_id=None, limit=100):
        return self.list(user_id=user_id, upcoming=True, limit=limit)

    def cancel(self, reminder_id, user_id=None):
        reminder = self.get(reminder_id, user_id)
        if not reminder:
            return False
        with self.database._get_connection() as conn:
            # Once delivery started, its outcome cannot be safely cancelled.
            changed = conn.execute("UPDATE reminders SET status='cancelled', updated_at=? WHERE id=? AND status IN ('pending','claimed','failed')", (self._now().isoformat(), reminder_id)).rowcount
        return bool(changed)

    async def dispatch_due(self, now=None):
        now = _aware(now) if now is not None else self._now()
        conn = self.database._get_connection()
        ids = [row["id"] for row in conn.execute("SELECT id FROM reminders WHERE status='pending' AND due_timestamp<=? AND next_attempt_at<=? ORDER BY due_timestamp", (now.timestamp(), now.timestamp())).fetchall()]
        outcomes = []
        for reminder_id in ids:
            with conn:
                claimed = conn.execute("UPDATE reminders SET status='claimed', claimed_at=?, updated_at=? WHERE id=? AND status='pending' AND next_attempt_at<=?", (now.isoformat(), now.isoformat(), reminder_id, now.timestamp())).rowcount
            if not claimed:
                continue
            with conn:
                started = conn.execute("UPDATE reminders SET status='delivering', attempts=attempts+1, updated_at=? WHERE id=? AND status='claimed'", (now.isoformat(), reminder_id)).rowcount
            if not started:
                continue
            reminder = self.get(reminder_id)
            try:
                outcome = self.deliver(reminder)
                if inspect.isawaitable(outcome):
                    outcome = await outcome
                if outcome is False or (isinstance(outcome, dict) and (outcome.get("success") is not True or outcome.get("error"))):
                    raise RuntimeError(outcome.get("error") if isinstance(outcome, dict) and outcome.get("error") else "Delivery callback did not confirm success")
            except RetryableDeliveryError as exc:
                retry = reminder["attempts"] < self.max_attempts
                with conn:
                    conn.execute("UPDATE reminders SET status=?, error=?, next_attempt_at=?, updated_at=? WHERE id=? AND status='delivering'", ("pending" if retry else "failed", str(exc), now.timestamp() + min(3600, 30 * 2 ** (reminder["attempts"] - 1)), self._now().isoformat(), reminder_id))
            except asyncio.CancelledError:
                with conn:
                    conn.execute("UPDATE reminders SET status='failed', error=?, updated_at=? WHERE id=? AND status='delivering'", ("Delivery was interrupted; its outcome is unknown. No automatic retry.", self._now().isoformat(), reminder_id))
                raise
            except Exception as exc:
                with conn:
                    conn.execute("UPDATE reminders SET status='failed', error=?, updated_at=? WHERE id=? AND status='delivering'", (str(exc), self._now().isoformat(), reminder_id))
                logger.warning("Reminder %s delivery failed: %s", reminder_id, exc)
            else:
                delivered = self._now().isoformat()
                with conn:
                    conn.execute("UPDATE reminders SET status='delivered', delivered_at=?, error='', updated_at=? WHERE id=? AND status='delivering'", (delivered, delivered, reminder_id))
            outcomes.append(self.get(reminder_id))
        return outcomes

    async def _loop(self):
        while True:
            try:
                await self.dispatch_due()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Reminder polling failed")
            await asyncio.sleep(self.poll_interval)

    async def start(self):
        if not self._job or self._job.done():
            self._job = asyncio.create_task(self._loop(), name="lyra-reminders")

    async def stop(self):
        if self._job:
            self._job.cancel()
            try:
                await self._job
            except asyncio.CancelledError:
                pass
            self._job = None
