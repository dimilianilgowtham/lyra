"""
LYRA — Session Memory
Persists user preferences, name, and conversation context across sessions.
Uses the existing SQLite user profile; legacy JSON is retained for recovery.
"""

import json
import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from config import settings
from core.database import DatabaseManager, db

logger = logging.getLogger("LYRA.Memory")
SESSION_MEMORY_KEY = "session_memory"
LEGACY_IMPORTED_KEY = "session_memory_json_imported"


class SessionMemory:
    """Persistent session memory for LYRA."""

    def __init__(self, data_dir: str | Path = None, database: DatabaseManager = None, user_id: str = "default_user"):
        self.data_dir = Path(data_dir if data_dir is not None else settings.DATA_DIR)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        # Custom directories remain self-contained; normal startup shares the
        # configured database singleton used by conversations and personal memory.
        self.database = database if database is not None else (
            DatabaseManager(str(self.data_dir / "lyra.db")) if data_dir is not None else db
        )
        self.user_id = user_id
        self.memory_file = self.data_dir / "session_memory.json"
        if data_dir is None and os.getenv("LYRA_LEGACY_SESSION_FILE"):
            self.memory_file = Path(settings.LEGACY_SESSION_FILE)
        self.memory: dict = self._load()

    @staticmethod
    def _preferences(user: dict) -> dict:
        preferences = json.loads(user["preferences_json"])
        if not isinstance(preferences, dict):
            raise ValueError("Profile preferences must be an object")
        return preferences

    @classmethod
    def _merge(cls, older: dict, newer: dict) -> dict:
        """Keep legacy context while allowing current scalar values to win."""
        merged = dict(older)
        for key, value in newer.items():
            previous = merged.get(key)
            if isinstance(previous, dict) and isinstance(value, dict):
                merged[key] = cls._merge(previous, value)
            elif isinstance(previous, list) and isinstance(value, list):
                merged[key] = previous + [item for item in value if item not in previous]
            else:
                merged[key] = value
        return merged

    def _load(self) -> dict:
        """Merge recoverable legacy context once without rewriting its source."""
        user = self.database.get_or_create_user(self.user_id)
        preferences = self._preferences(user)
        stored = preferences.get(SESSION_MEMORY_KEY)
        if stored is not None and not isinstance(stored, dict):
            raise ValueError("Stored session memory must be an object")

        memory = self._default_memory()
        memory["user_name"] = user.get("name", "")
        imported = False
        if (self.user_id == "default_user" and self.memory_file.exists()
                and not preferences.get(LEGACY_IMPORTED_KEY)):
            try:
                with self.memory_file.open("r", encoding="utf-8") as source:
                    legacy = json.load(source)
                if not isinstance(legacy, dict):
                    raise ValueError("Legacy session memory must be an object")
                memory.update(legacy)
                imported = True
                logger.info("Imported legacy session memory into SQLite; recovery file retained")
            except (ValueError, OSError) as error:
                logger.warning("Legacy memory could not be imported; original file retained: %s", error)

        if stored is not None:
            memory = self._merge(memory, stored)
        if stored is None or imported or memory.get("personality_mode") in ("friday", "jarvis"):
            self._persist(memory, imported=imported)
        return memory

    def _refresh(self):
        """Read the current session before editing, including other writers' work."""
        user = self.database.get_or_create_user(self.user_id)
        stored = self._preferences(user).get(SESSION_MEMORY_KEY)
        if not isinstance(stored, dict):
            raise ValueError("Stored session memory must be an object")
        self.memory = {**self._default_memory(), **stored}

    def _persist(self, memory: dict, imported: bool = False):
        """Preserve unrelated preferences and mark only successful imports."""
        if memory.get("personality_mode") in ("friday", "jarvis"):
            memory["personality_mode"] = "balanced"
        user = self.database.get_or_create_user(self.user_id, name=memory.get("user_name", ""))
        preferences = self._preferences(user)
        preferences[SESSION_MEMORY_KEY] = memory
        if imported:
            preferences[LEGACY_IMPORTED_KEY] = True
        self.database.update_user_preferences(self.user_id, preferences)

    def _default_memory(self) -> dict:
        return {
            "user_name": "",
            "personality_mode": "balanced",
            "topics_discussed": [],
            "frequent_commands": {},
            "session_count": 0,
            "first_seen": datetime.now().isoformat(),
            "last_seen": "",
            "preferences": {},
            "notes": [],
        }

    def save(self):
        """Persist memory to the existing SQLite user profile."""
        self.memory["last_seen"] = datetime.now().isoformat()
        try:
            self._persist(self.memory)
        except (sqlite3.Error, OSError) as e:
            logger.error(f"Failed to save memory: {e}")

    # ── Getters ─────────────────────────────────────────────────

    @property
    def user_name(self) -> str:
        self._refresh()
        return self.memory.get("user_name", "")

    @property
    def session_count(self) -> int:
        self._refresh()
        return self.memory.get("session_count", 0)

    @property
    def personality_mode(self) -> str:
        self._refresh()
        mode = self.memory.get("personality_mode", "balanced")
        if mode in ("friday", "jarvis"):
            mode = "balanced"
            self.memory["personality_mode"] = mode
            self.save()
        return mode

    def get_context_summary(self) -> str:
        """Generate a context string for the AI system prompt."""
        self._refresh()
        parts = []

        if self.user_name:
            parts.append(f"User's name: {self.user_name}")

        session_count = self.session_count
        if session_count > 1:
            parts.append(f"This is session #{session_count} with this user.")

        topics = self.memory.get("topics_discussed", [])[-10:]
        if topics:
            parts.append(f"Recent topics: {', '.join(topics)}")

        freq = self.memory.get("frequent_commands", {})
        if freq:
            top_cmds = sorted(freq.items(), key=lambda x: x[1], reverse=True)[:5]
            cmds_str = ", ".join(f"{cmd}({count}x)" for cmd, count in top_cmds)
            parts.append(f"Frequently used: {cmds_str}")

        return "\n".join(parts) if parts else ""

    # ── Setters ─────────────────────────────────────────────────

    def set_user_name(self, name: str):
        """Store user's name."""
        self._refresh()
        self.memory["user_name"] = name
        self.save()
        logger.info(f"👤 User name set: {name}")

    def set_personality(self, mode: str):
        """Store preferred personality mode."""
        self._refresh()
        self.memory["personality_mode"] = mode
        self.save()

    def add_topic(self, topic: str):
        """Track a discussed topic."""
        self._refresh()
        topics = self.memory.setdefault("topics_discussed", [])
        if topic not in topics[-5:]:  # Avoid duplicates in recent history
            topics.append(topic)
            # Keep last 50 topics
            if len(topics) > 50:
                self.memory["topics_discussed"] = topics[-50:]
            self.save()

    def track_command(self, command: str):
        """Track command frequency."""
        self._refresh()
        # Normalize to category
        lower = command.lower().strip()
        if lower.startswith("open "):
            key = f"open:{lower.split()[1] if len(lower.split()) > 1 else 'app'}"
        elif any(lower.startswith(w) for w in ("volume", "mute", "unmute")):
            key = "volume_control"
        elif any(lower.startswith(w) for w in ("what", "how", "why", "who", "when")):
            key = "knowledge_question"
        elif any(lower.startswith(w) for w in ("search", "find", "grep")):
            key = "search"
        else:
            key = "chat"

        freq = self.memory.setdefault("frequent_commands", {})
        freq[key] = freq.get(key, 0) + 1
        self.save()

    def add_note(self, note: str):
        """Add a user note/reminder."""
        self._refresh()
        self.memory.setdefault("notes", []).append({
            "text": note,
            "created": datetime.now().isoformat(),
        })
        self.save()

    def increment_session(self):
        """Mark a new session."""
        self._refresh()
        self.memory["session_count"] = self.memory.get("session_count", 0) + 1
        self.save()

    def detect_user_name(self, text: str) -> str | None:
        """Try to detect user's name from conversation text."""
        import re

        patterns = [
            r"(?:my name is|i'm|i am|call me|they call me)\s+([A-Z][a-z]+)",
            r"(?:name's)\s+([A-Z][a-z]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                name = match.group(1).strip()
                if len(name) > 1 and name.lower() not in ("the", "a", "an", "lyra", "siri", "alexa"):
                    self.set_user_name(name)
                    return name
        return None
