"""An installed backend keeps mutable state outside its application bundle."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


BACKEND_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BACKEND_DIR.parent


class TestInstalledPaths(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="lyra-installed-paths-")
        self.root = Path(self.directory.name).resolve()
        self.data = self.root / "Application Support" / "Lyra" / "data"
        self.config = self.root / "Application Support" / "Lyra" / "config"
        self.config.mkdir(parents=True)

    def tearDown(self):
        self.directory.cleanup()

    def run_backend(self, code, **overrides):
        env = os.environ.copy()
        # Every subprocess uses temporary mutable storage and synthetic secrets.
        for key in ("DATABASE_PATH", "BACKEND_AUTH_TOKEN", "LYRA_LEGACY_SESSION_FILE",
                    "LYRA_ENV_FILE", "LOCAL_STT_MODEL_DIR", "OPENAI_API_KEY"):
            env.pop(key, None)
        env.update({"LYRA_DATA_DIR": str(self.data), "LYRA_CONFIG_DIR": str(self.config),
                    "DATABASE_PATH": str(self.data / "lyra.db"),
                    "BACKEND_AUTH_TOKEN": "synthetic-test-token-never-used-for-real-access",
                    "PYTHONPATH": str(BACKEND_DIR), "PYTHONDONTWRITEBYTECODE": "1"})
        env.update(overrides)
        result = subprocess.run([sys.executable, "-c", code], cwd=self.root, env=env,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout.strip().splitlines()[-1])

    def test_storage_and_local_model_follow_installed_data_directory(self):
        state = self.run_backend("""
import json
from pathlib import Path
from config import settings
from voice.local_transcription import LocalTranscriber
token = Path(settings.DATA_DIR) / '.backend-auth-token'
print(json.dumps({'data': settings.DATA_DIR, 'database': settings.DB_PATH,
                  'token_exists': token.is_file(), 'token_mode': token.stat().st_mode & 0o777,
                  'model': str(LocalTranscriber().model_dir)}))
""", DATABASE_PATH="", BACKEND_AUTH_TOKEN="")
        self.assertEqual(state["data"], str(self.data))
        self.assertEqual(state["database"], str(self.data / "lyra.db"))
        self.assertTrue(state["token_exists"])
        self.assertEqual(state["token_mode"], 0o600)
        self.assertEqual(state["model"], str(self.data / "models" / "faster-whisper-tiny"))

    def test_user_config_loads_and_process_environment_has_priority(self):
        (self.config / ".env").write_text("DEFAULT_LOCAL_MODEL=installed-model\nOPENAI_API_KEY=synthetic-key\n")
        state = self.run_backend("""
import json
from config import settings
print(json.dumps({'model': settings.DEFAULT_LOCAL_MODEL,
                  'key_loaded': settings.OPENAI_API_KEY == 'synthetic-key'}))
""", DEFAULT_LOCAL_MODEL="process-model")
        self.assertEqual(state["model"], "process-model")
        self.assertTrue(state["key_loaded"])

    def test_explicit_env_file_overrides_config_directory_file(self):
        (self.config / ".env").write_text("DEFAULT_LOCAL_MODEL=directory-model\n")
        explicit = self.root / "custom.env"
        explicit.write_text("DEFAULT_LOCAL_MODEL=explicit-model\n")
        state = self.run_backend("""
import json
from config import settings
print(json.dumps({'model': settings.DEFAULT_LOCAL_MODEL}))
""", LYRA_ENV_FILE=str(explicit))
        self.assertEqual(state["model"], "explicit-model")

    def test_relative_legacy_database_path_is_independent_of_working_directory(self):
        state = self.run_backend("""
import json
from config import settings
print(json.dumps({'database': settings.DB_PATH}))
""", DATABASE_PATH="lyra-backend/data/lyra.db")
        self.assertEqual(state["database"], str(BACKEND_DIR / "data" / "lyra.db"))

    def test_explicit_legacy_session_import_preserves_recovery_file(self):
        legacy = self.root / "old-session.json"
        original = json.dumps({"user_name": "Installed user", "notes": [{"text": "Keep me"}]}).encode()
        legacy.write_bytes(original)
        state = self.run_backend("""
import json
from core.session_memory import SessionMemory
memory = SessionMemory()
print(json.dumps({'name': memory.user_name, 'notes': memory.memory['notes']}))
""", LYRA_LEGACY_SESSION_FILE=str(legacy))
        self.assertEqual(state["name"], "Installed user")
        self.assertEqual(state["notes"], [{"text": "Keep me"}])
        self.assertEqual(legacy.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
