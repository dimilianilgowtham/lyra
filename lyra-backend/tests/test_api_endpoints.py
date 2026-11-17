"""
Integration tests for LYRA REST API Endpoints:
Conversations, Messages, Memories, Audit Log, and Health.
"""

import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient
from main import app
from core.database import db
from config import settings


class TestAPIEndpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app, headers={"Authorization": f"Bearer {settings.BACKEND_AUTH_TOKEN}"})

    def test_health_endpoint(self):
        """Verify /api/health returns online status and system info."""
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "online")
        self.assertEqual(data["system"], "LYRA")
        self.assertEqual(data["database"], "sqlite_wal")
        self.assertIn("providers", data)

    def test_conversation_crud_endpoints(self):
        """Verify creating, listing, and deleting conversations via REST API."""
        # 1. Create conversation
        create_resp = self.client.post("/api/conversations", json={
            "user_id": "test_user_api",
            "title": "API Test Chat",
        })
        self.assertEqual(create_resp.status_code, 200)
        conv = create_resp.json()
        conv_id = conv["id"]
        self.assertEqual(conv["title"], "API Test Chat")

        # 2. List conversations
        list_resp = self.client.get("/api/conversations?user_id=test_user_api")
        self.assertEqual(list_resp.status_code, 200)
        convs = list_resp.json()["conversations"]
        self.assertTrue(any(c["id"] == conv_id for c in convs))

        # 3. Get messages for empty conversation
        msgs_resp = self.client.get(f"/api/conversations/{conv_id}/messages")
        self.assertEqual(msgs_resp.status_code, 200)
        self.assertEqual(len(msgs_resp.json()["messages"]), 0)

        # 4. Delete conversation
        del_resp = self.client.delete(f"/api/conversations/{conv_id}")
        self.assertEqual(del_resp.status_code, 200)
        self.assertTrue(del_resp.json()["success"])

    def test_memory_crud_endpoints(self):
        """Verify consented personal memory CRUD operations via REST API."""
        user_id = "test_user_mem"

        # 1. Add memory
        add_resp = self.client.post("/api/memories", json={
            "user_id": user_id,
            "fact": "Prefers concise voice responses",
            "category": "preference",
            "consented": True,
        })
        self.assertEqual(add_resp.status_code, 200)
        mem = add_resp.json()
        mem_id = mem["id"]

        # 2. List memories
        list_resp = self.client.get(f"/api/memories?user_id={user_id}")
        self.assertEqual(list_resp.status_code, 200)
        mems = list_resp.json()["memories"]
        self.assertTrue(any(m["id"] == mem_id for m in mems))

        # 3. Update memory consent
        upd_resp = self.client.put(f"/api/memories/{mem_id}", json={
            "consented": False,
        })
        self.assertEqual(upd_resp.status_code, 200)
        self.assertTrue(upd_resp.json()["success"])

        # 4. Delete memory
        del_resp = self.client.delete(f"/api/memories/{mem_id}")
        self.assertEqual(del_resp.status_code, 200)
        self.assertTrue(del_resp.json()["success"])

    def test_audit_log_endpoint(self):
        """Verify /api/audit-log returns logged actions."""
        # Log an action
        db.log_action(
            tool="read_file",
            arguments={"path": "package.json"},
            impact_summary="Read-only file inspection",
            approved=True,
            user_decision="Approved",
            result_summary="File content read successfully",
            duration_ms=12.0,
        )

        response = self.client.get("/api/audit-log")
        self.assertEqual(response.status_code, 200)
        logs = response.json()["logs"]
        self.assertTrue(len(logs) > 0)
        self.assertEqual(logs[0]["tool"], "read_file")


if __name__ == "__main__":
    unittest.main()

