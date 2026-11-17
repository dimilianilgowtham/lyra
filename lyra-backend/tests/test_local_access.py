"""Local API access must protect every execution route."""
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from main import app
from config import settings


class TestLocalAccess(unittest.TestCase):
    def test_unauthenticated_terminal_cannot_execute(self):
        with patch("tools.shell.execute_command", new_callable=AsyncMock) as execute:
            execute.return_value = {"success": True, "stdout": "should not run", "exit_code": 0}
            response = TestClient(app).post("/api/terminal/exec", json={"command": "echo blocked"})
        self.assertEqual(response.status_code, 401)
        execute.assert_not_awaited()

    def test_foreign_origin_cannot_bootstrap_local_session(self):
        response = TestClient(app).get("/api/session", headers={"Origin": "https://untrusted.example"})
        self.assertEqual(response.status_code, 403)

    def test_browser_session_cookie_is_http_only_and_authenticates(self):
        client = TestClient(app)
        response = client.get("/api/session", headers={"Origin": "http://127.0.0.1:3000"})
        self.assertEqual(response.status_code, 200)
        cookie = response.headers["set-cookie"].lower()
        self.assertIn("httponly", cookie)
        self.assertIn("samesite=strict", cookie)
        self.assertNotIn(getattr(settings, "BACKEND_AUTH_TOKEN", "missing-token"), response.text)
        self.assertEqual(client.get("/api/memories").status_code, 200)

    def test_websocket_requires_local_session(self):
        with self.assertRaises(WebSocketDisconnect) as rejected:
            with TestClient(app).websocket_connect("/ws"):
                pass
        self.assertEqual(rejected.exception.code, 1008)


if __name__ == "__main__":
    unittest.main()
