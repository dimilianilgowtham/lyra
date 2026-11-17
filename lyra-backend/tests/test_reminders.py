"""Reminder scheduling, restart and delivery idempotency regressions."""
import asyncio
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.database import DatabaseManager
try:
    from core.reminders import ReminderService, RetryableDeliveryError
except ImportError:
    ReminderService = None
    RetryableDeliveryError = None


class ReminderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = DatabaseManager(str(Path(self.directory.name) / "reminders.db"))
        self.now = datetime(2026, 10, 14, 9, tzinfo=timezone.utc)
        self.services = []

    async def asyncTearDown(self):
        for service in self.services:
            await service.stop()
        self.directory.cleanup()

    def service(self, deliver):
        self.assertIsNotNone(ReminderService, "ReminderService must exist")
        service = ReminderService(self.db, deliver, clock=lambda: self.now, poll_interval=.01)
        self.services.append(service)
        return service

    async def test_delivers_once_only_when_due_and_preserves_timezone(self):
        delivered = []
        async def deliver(reminder):
            delivered.append(reminder["id"])
        service = self.service(deliver)
        reminder = service.create("Tea", "2026-10-14T15:00:00+05:30", user_id="alice")
        self.assertEqual(service.list(user_id="bob"), [])
        self.assertEqual(service.list(upcoming=True)[0]["text"], "Tea")
        await service.dispatch_due(self.now)
        self.assertEqual(delivered, [])
        self.now += timedelta(minutes=30)
        await service.dispatch_due(self.now)
        await service.dispatch_due(self.now)
        self.assertEqual(delivered, [reminder["id"]])
        self.assertEqual(service.get(reminder["id"])["status"], "delivered")

    async def test_overdue_reminder_is_delivered_after_restart(self):
        delivered = asyncio.Event()
        async def deliver(reminder):
            delivered.set()
        first = self.service(deliver)
        reminder = first.create("Overdue", self.now.isoformat())
        second = self.service(deliver)
        await second.start()
        await asyncio.wait_for(delivered.wait(), 1)
        for _ in range(20):
            if second.get(reminder["id"])["status"] == "delivered":
                break
            await asyncio.sleep(.001)
        self.assertEqual(second.get(reminder["id"])["status"], "delivered")

    async def test_concurrent_dispatch_claims_only_one_delivery(self):
        calls = []
        async def deliver(reminder):
            calls.append(reminder["id"])
            await asyncio.sleep(.01)
        service = self.service(deliver)
        reminder = service.create("Only once", self.now.isoformat())
        await asyncio.gather(service.dispatch_due(self.now), service.dispatch_due(self.now))
        self.assertEqual(calls, [reminder["id"]])

    async def test_ambiguous_callback_failure_is_not_retried_automatically(self):
        calls = []
        async def deliver(reminder):
            calls.append(reminder["id"])
            raise RuntimeError("Notification result unknown")
        service = self.service(deliver)
        reminder = service.create("Failure", self.now.isoformat())
        await service.dispatch_due(self.now)
        await service.dispatch_due(self.now + timedelta(days=1))
        self.assertEqual(calls, [reminder["id"]])
        self.assertEqual(service.get(reminder["id"])["status"], "failed")
        self.assertIn("unknown", service.get(reminder["id"])["error"])

    async def test_structured_error_does_not_count_as_confirmed_delivery(self):
        async def deliver(reminder):
            return {"error": "Notification was rejected"}
        service = self.service(deliver)
        reminder = service.create("Error result", self.now.isoformat())
        await service.dispatch_due(self.now)
        self.assertEqual(service.get(reminder["id"])["status"], "failed")

    async def test_restart_during_delivery_marks_ambiguous_failure(self):
        calls = []
        async def deliver(reminder):
            calls.append(reminder["id"])
        service = self.service(deliver)
        reminder = service.create("Crash recovery", self.now.isoformat())
        with self.db._get_connection() as conn:
            conn.execute("UPDATE reminders SET status='delivering' WHERE id=?", (reminder["id"],))
        restarted = self.service(deliver)
        await restarted.dispatch_due(self.now)
        self.assertEqual(calls, [])
        self.assertEqual(restarted.get(reminder["id"])["status"], "failed")

    async def test_known_undelivered_failure_retries_then_succeeds(self):
        attempts = []
        async def deliver(reminder):
            attempts.append(reminder["id"])
            if len(attempts) == 1:
                raise RetryableDeliveryError("Notifier was not available")
        service = self.service(deliver)
        reminder = service.create("Retry", self.now.isoformat())
        await service.dispatch_due(self.now)
        self.assertEqual(service.get(reminder["id"])["status"], "pending")
        await service.dispatch_due(self.now + timedelta(minutes=5))
        self.assertEqual(service.get(reminder["id"])["status"], "delivered")
        self.assertEqual(len(attempts), 2)

    async def test_cancel_and_invalid_inputs_do_not_deliver(self):
        calls = []
        async def deliver(reminder):
            calls.append(reminder)
        service = self.service(deliver)
        with self.assertRaises(ValueError):
            service.create("Tea", "2026-10-14T10:00:00")
        with self.assertRaises(ValueError):
            service.create(" ", self.now.isoformat())
        reminder = service.create("Cancelled", self.now.isoformat(), user_id="alice")
        with self.assertRaises(PermissionError):
            service.cancel(reminder["id"], user_id="bob")
        self.assertTrue(service.cancel(reminder["id"], user_id="alice"))
        await service.dispatch_due(self.now)
        self.assertEqual(calls, [])
        self.assertEqual(service.get(reminder["id"])["status"], "cancelled")


if __name__ == "__main__":
    unittest.main()
