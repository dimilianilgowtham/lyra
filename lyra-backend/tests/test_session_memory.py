"""Regression tests for session memory in the existing SQLite user profile."""

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from core.database import DatabaseManager
from core.session_memory import SessionMemory


class TestSessionMemory(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)
        self.db = DatabaseManager(str(self.data_dir / "profiles.db"))
        self.legacy_file = self.data_dir / "session_memory.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def stored_preferences(self, user_id="default_user"):
        user = self.db.get_or_create_user(user_id)
        return json.loads(user["preferences_json"])

    def legacy_memory(self):
        return {
            "user_name": "Anil",
            "personality_mode": "jarvis",
            "topics_discussed": ["SQLite", "voice"],
            "frequent_commands": {"open:terminal": 4},
            "session_count": 12,
            "first_seen": "2025-01-01T00:00:00",
            "last_seen": "2025-03-01T00:00:00",
            "preferences": {"language": "en-IN"},
            "notes": [{"text": "Keep the project notes", "created": "2025-02-01"}],
            "custom_context": {"project": "Lyra"},
        }

    def write_legacy(self, memory):
        self.legacy_file.write_text(json.dumps(memory, indent=2), encoding="utf-8")
        return self.legacy_file.read_bytes()

    def test_imports_all_legacy_fields_without_changing_recovery_file(self):
        legacy = self.legacy_memory()
        original = self.write_legacy(legacy)

        memory = SessionMemory(data_dir=self.data_dir, database=self.db)

        expected = {**legacy, "personality_mode": "balanced"}
        self.assertEqual(memory.memory, expected)
        self.assertEqual(self.stored_preferences()["session_memory"], expected)
        self.assertEqual(self.legacy_file.read_bytes(), original)
        self.assertEqual(self.db.get_or_create_user()["name"], "Anil")

    def test_restart_uses_sqlite_after_one_time_import(self):
        original = self.write_legacy(self.legacy_memory())
        memory = SessionMemory(data_dir=self.data_dir, database=self.db)
        memory.add_note("New SQLite note")
        memory.add_topic("Current topic")
        memory.increment_session()

        restarted_db = DatabaseManager(str(self.db.db_path))
        restarted = SessionMemory(data_dir=self.data_dir, database=restarted_db)

        self.assertEqual(restarted.session_count, 13)
        self.assertEqual(restarted.memory["topics_discussed"][-1], "Current topic")
        self.assertEqual(restarted.memory["notes"][-1]["text"], "New SQLite note")
        self.assertEqual(len(restarted.memory["notes"]), 2)
        self.assertEqual(self.legacy_file.read_bytes(), original)

    def test_saves_preserve_existing_and_recently_updated_profile_preferences(self):
        self.db.get_or_create_user(name="Existing profile name")
        self.db.update_user_preferences("default_user", {"theme": "light", "voice": {"enabled": True}})
        self.write_legacy(self.legacy_memory())
        memory = SessionMemory(data_dir=self.data_dir, database=self.db)

        prefs = self.stored_preferences()
        prefs["theme"] = "dark"
        prefs["new_preference"] = ["keep", "this"]
        self.db.update_user_preferences("default_user", prefs)
        memory.increment_session()

        stored = self.stored_preferences()
        self.assertEqual(stored["theme"], "dark")
        self.assertEqual(stored["voice"], {"enabled": True})
        self.assertEqual(stored["new_preference"], ["keep", "this"])
        self.assertEqual(stored["session_memory"]["preferences"], {"language": "en-IN"})
        self.assertEqual(self.db.get_or_create_user()["name"], "Existing profile name")

    def test_persists_new_session_without_creating_json(self):
        memory = SessionMemory(data_dir=self.data_dir, database=self.db)
        memory.set_user_name("Anil")
        memory.set_personality("focused")
        memory.track_command("open terminal")
        memory.add_note("Remember this")
        memory.increment_session()
        restarted = SessionMemory(data_dir=self.data_dir, database=self.db)

        self.assertEqual(restarted.user_name, "Anil")
        self.assertEqual(restarted.personality_mode, "focused")
        self.assertEqual(restarted.session_count, 1)
        self.assertEqual(restarted.memory["frequent_commands"], {"open:terminal": 1})
        self.assertEqual(restarted.memory["notes"][0]["text"], "Remember this")
        self.assertFalse(self.legacy_file.exists())

    def test_explicit_data_directory_keeps_storage_isolated(self):
        memory = SessionMemory(data_dir=self.data_dir)
        memory.set_user_name("Isolated user")
        isolated_db = DatabaseManager(str(self.data_dir / "lyra.db"))
        prefs = json.loads(isolated_db.get_or_create_user()["preferences_json"])

        self.assertEqual(prefs.get("session_memory", {}).get("user_name"), "Isolated user")
        self.assertFalse(self.legacy_file.exists())

    def test_default_constructor_uses_configured_database(self):
        with patch("core.session_memory.db", self.db), patch("core.session_memory.settings.DATA_DIR", str(self.data_dir)):
            memory = SessionMemory()
            memory.increment_session()

        self.assertEqual(self.stored_preferences()["session_memory"]["session_count"], 1)
        self.assertFalse((self.data_dir / "lyra.db").exists())

    def test_legacy_global_profile_is_not_assigned_to_another_user(self):
        original = self.write_legacy(self.legacy_memory())
        memory = SessionMemory(data_dir=self.data_dir, database=self.db, user_id="another_user")
        memory.increment_session()

        self.assertEqual(memory.user_name, "")
        self.assertEqual(memory.memory["notes"], [])
        self.assertEqual(memory.session_count, 1)
        self.assertEqual(self.stored_preferences("another_user")["session_memory"]["session_count"], 1)
        self.assertNotIn("session_memory", self.stored_preferences())
        self.assertEqual(self.legacy_file.read_bytes(), original)

    def test_invalid_legacy_json_is_retained(self):
        self.legacy_file.write_text("{incomplete", encoding="utf-8")
        with self.assertLogs("LYRA.Memory", level="WARNING"):
            memory = SessionMemory(data_dir=self.data_dir, database=self.db)
        memory.increment_session()

        self.assertEqual(self.legacy_file.read_text(encoding="utf-8"), "{incomplete")
        self.assertEqual(self.stored_preferences()["session_memory"]["session_count"], 1)

    def test_partial_sqlite_metadata_merges_legacy_notes_and_topics_once(self):
        legacy = self.legacy_memory()
        original = self.write_legacy(legacy)
        current_note = {"text": "Already in SQLite", "created": "2026-01-01"}
        self.db.get_or_create_user()
        self.db.update_user_preferences("default_user", {
            "theme": "light",
            "session_memory": {
                "notes": [current_note],
                "topics_discussed": ["SQLite", "new topic"],
                "session_count": 15,
                "preferences": {"voice": "on"},
            },
        })

        memory = SessionMemory(data_dir=self.data_dir, database=self.db)
        self.assertEqual(memory.memory["notes"], [legacy["notes"][0], current_note])
        self.assertEqual(memory.memory["topics_discussed"], ["SQLite", "voice", "new topic"])
        self.assertEqual(memory.memory["preferences"], {"language": "en-IN", "voice": "on"})
        self.assertEqual(memory.session_count, 15)
        self.assertEqual(self.stored_preferences()["theme"], "light")

        restarted = SessionMemory(data_dir=self.data_dir, database=self.db)
        self.assertEqual(restarted.memory["notes"], memory.memory["notes"])
        self.assertEqual(self.legacy_file.read_bytes(), original)

    def test_repaired_legacy_file_can_be_imported_after_an_unsuccessful_attempt(self):
        self.legacy_file.write_text("{incomplete", encoding="utf-8")
        with self.assertLogs("LYRA.Memory", level="WARNING"):
            memory = SessionMemory(data_dir=self.data_dir, database=self.db)
        memory.add_note("New note while source needs recovery")
        self.write_legacy(self.legacy_memory())

        restarted = SessionMemory(data_dir=self.data_dir, database=self.db)

        self.assertEqual(restarted.memory["notes"][0]["text"], "Keep the project notes")
        self.assertEqual(restarted.memory["notes"][1]["text"], "New note while source needs recovery")

    def test_two_session_objects_preserve_each_others_notes_and_session_count(self):
        first = SessionMemory(data_dir=self.data_dir, database=self.db)
        second = SessionMemory(data_dir=self.data_dir, database=DatabaseManager(str(self.db.db_path)))

        first.add_note("First writer")
        second.add_note("Second writer")
        first.increment_session()
        second.increment_session()

        stored = self.stored_preferences()["session_memory"]
        self.assertEqual([note["text"] for note in stored["notes"]], ["First writer", "Second writer"])
        self.assertEqual(first.session_count, 2)
        self.assertEqual(second.session_count, 2)

    def test_non_object_profile_preferences_are_not_overwritten(self):
        self.db.get_or_create_user()
        self.db.update_user_preferences("default_user", ["saved unexpected value"])

        with self.assertRaisesRegex(ValueError, "preferences must be an object"):
            SessionMemory(data_dir=self.data_dir, database=self.db)

        self.assertEqual(self.stored_preferences(), ["saved unexpected value"])

    def test_malformed_profile_preferences_are_not_overwritten(self):
        self.db.get_or_create_user()
        with sqlite3.connect(self.db.db_path) as connection:
            connection.execute("UPDATE users SET preferences_json = ? WHERE id = ?", ("{incomplete", "default_user"))

        with self.assertRaises(json.JSONDecodeError):
            SessionMemory(data_dir=self.data_dir, database=self.db)

        self.assertEqual(self.db.get_or_create_user()["preferences_json"], "{incomplete")

    def test_legacy_personality_names_are_normalized_when_set(self):
        memory = SessionMemory(data_dir=self.data_dir, database=self.db)
        memory.set_personality("friday")

        self.assertEqual(self.stored_preferences()["session_memory"]["personality_mode"], "balanced")
        self.assertEqual(memory.personality_mode, "balanced")


if __name__ == "__main__":
    unittest.main()
