"""
LYRA Database Manager — SQLite Persistence
Provides thread-safe storage for users, conversations, multi-turn messages,
consented personal memories, notes, and action audit trails.
"""

import json
import hashlib
import logging
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from config import settings

logger = logging.getLogger("LYRA.Database")


class DatabaseManager:
    """Thread-safe SQLite manager for durable conversation and memory persistence."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = Path(db_path or settings.DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(
                str(self.db_path),
                timeout=20.0,
                check_same_thread=False,
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA foreign_keys=ON;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            self._local.conn = conn
        return self._local.conn

    def _init_db(self):
        """Create tables and indexes if they do not exist."""
        conn = self._get_connection()
        with conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL DEFAULT '',
                preferences_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                last_seen TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT 'New Conversation',
                summary TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                model TEXT NOT NULL DEFAULT '',
                tokens INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, created_at);

            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                fact TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'preference',
                consented INTEGER NOT NULL DEFAULT 1,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_memories_user ON memories(user_id, is_active, consented);

            CREATE TABLE IF NOT EXISTS notes (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                tags TEXT NOT NULL DEFAULT '',
                project TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS action_audit_log (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                tool TEXT NOT NULL,
                arguments_json TEXT NOT NULL DEFAULT '{}',
                impact_summary TEXT NOT NULL DEFAULT '',
                approved INTEGER NOT NULL DEFAULT 0,
                user_decision TEXT NOT NULL DEFAULT '',
                result_summary TEXT NOT NULL DEFAULT '',
                duration_ms REAL NOT NULL DEFAULT 0.0
            );

            CREATE INDEX IF NOT EXISTS idx_audit_time ON action_audit_log(timestamp DESC);

            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                conversation_id TEXT,
                prompt TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                model TEXT NOT NULL DEFAULT '',
                provider TEXT NOT NULL DEFAULT '',
                mode TEXT NOT NULL DEFAULT 'agent',
                tool TEXT,
                arguments_json TEXT NOT NULL DEFAULT '{}',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                result_json TEXT,
                checkpoint_json TEXT NOT NULL DEFAULT '{}',
                error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks(user_id, updated_at DESC);
            CREATE TABLE IF NOT EXISTS task_events (
                task_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                type TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                PRIMARY KEY(task_id, seq),
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS reminders (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                text TEXT NOT NULL,
                due_at TEXT NOT NULL,
                due_timestamp REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_at REAL NOT NULL,
                claimed_at TEXT,
                delivered_at TEXT,
                error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(status, next_attempt_at);

            """)
            # Additive migration: existing messages and IDs remain intact.
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(messages)")}
            if "metadata_json" not in columns:
                conn.execute("ALTER TABLE messages ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'")
        logger.info(f"💾 Initialized SQLite database at {self.db_path}")

    # ── User Operations ───────────────────────────────────────────────

    def get_or_create_user(self, user_id: str = "default_user", name: str = "") -> dict:
        conn = self._get_connection()
        now = datetime.utcnow().isoformat()
        with conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            if row:
                if name and not row["name"]:
                    conn.execute("UPDATE users SET name = ?, last_seen = ? WHERE id = ?", (name, now, user_id))
                    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
                else:
                    conn.execute("UPDATE users SET last_seen = ? WHERE id = ?", (now, user_id))
                return dict(row)
            
            conn.execute(
                "INSERT INTO users (id, name, preferences_json, created_at, last_seen) VALUES (?, ?, ?, ?, ?)",
                (user_id, name, "{}", now, now),
            )
            return {
                "id": user_id,
                "name": name,
                "preferences_json": "{}",
                "created_at": now,
                "last_seen": now,
            }

    def update_user_preferences(self, user_id: str, preferences: dict) -> None:
        conn = self._get_connection()
        with conn:
            conn.execute(
                "UPDATE users SET preferences_json = ? WHERE id = ?",
                (json.dumps(preferences), user_id),
            )

    # ── Conversation Operations ───────────────────────────────────────

    def get_or_create_conversation(self, conversation_id: Optional[str], user_id: str = "default_user", title: str = "New Conversation") -> dict:
        conn = self._get_connection()
        self.get_or_create_user(user_id)
        now = datetime.utcnow().isoformat()
        with conn:
            if conversation_id:
                row = conn.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
                if row:
                    return dict(row)
            
            new_id = conversation_id or str(uuid.uuid4())
            conn.execute(
                "INSERT INTO conversations (id, user_id, title, summary, created_at, updated_at, metadata_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (new_id, user_id, title, "", now, now, "{}"),
            )
            return {
                "id": new_id,
                "user_id": user_id,
                "title": title,
                "summary": "",
                "created_at": now,
                "updated_at": now,
                "metadata_json": "{}",
            }

    def list_conversations(self, user_id: str = "default_user", limit: int = 50) -> list[dict]:
        conn = self._get_connection()
        rows = conn.execute(
            "SELECT * FROM conversations WHERE user_id = ? ORDER BY updated_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def update_conversation_summary(self, conversation_id: str, summary: str, title: Optional[str] = None) -> None:
        conn = self._get_connection()
        now = datetime.utcnow().isoformat()
        with conn:
            if title:
                conn.execute(
                    "UPDATE conversations SET summary = ?, title = ?, updated_at = ? WHERE id = ?",
                    (summary, title, now, conversation_id),
                )
            else:
                conn.execute(
                    "UPDATE conversations SET summary = ?, updated_at = ? WHERE id = ?",
                    (summary, now, conversation_id),
                )

    def delete_conversation(self, conversation_id: str) -> bool:
        conn = self._get_connection()
        with conn:
            res = conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
            return res.rowcount > 0

    def import_conversation(self, record: dict, user_id: str = "default_user") -> dict:
        """Atomically append a legacy chat once, without replacing stored messages.

        Explicit legacy message IDs are scoped to their chat; messages without
        IDs use a stable content hash plus their position in the legacy history.
        Imported metadata remains available in JSON even for unknown fields.
        """
        if not isinstance(record, dict):
            raise ValueError("Conversation must be an object")
        conversation_id = str(record.get("id") or record.get("conversation_id") or "").strip()
        if not conversation_id or len(conversation_id) > 200:
            raise ValueError("Conversation id is required and must be at most 200 characters")
        if record.get("user_id") not in (None, "", user_id):
            raise PermissionError("Conversation belongs to another user")
        metadata = record.get("metadata", record.get("metadata_json", {}))
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        if not isinstance(metadata, dict):
            raise ValueError("Conversation metadata must be an object")
        metadata = dict(metadata)
        if record.get("mode") is not None:
            metadata["mode"] = str(record["mode"])
        messages = record.get("messages", [])
        if not isinstance(messages, list):
            raise ValueError("Conversation messages must be an array")
        now = datetime.now(timezone.utc).isoformat()

        def timestamp(value):
            if value is None or value == "":
                return now
            try:
                if isinstance(value, (int, float)):
                    seconds = value / 1000 if abs(value) > 100000000000 else value
                    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()
                parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(timezone.utc).isoformat()
            except (ValueError, OverflowError, OSError) as exc:
                raise ValueError("Invalid conversation timestamp") from exc

        prepared = []
        for position, message in enumerate(messages):
            if not isinstance(message, dict) or message.get("role") not in {"user", "assistant", "system", "tool"}:
                raise ValueError("Each message must have a valid role")
            content = message.get("content", message.get("text", ""))
            if not isinstance(content, str):
                raise ValueError("Message content must be text")
            legacy_id = message.get("id")
            identity = legacy_id
            if identity is None or identity == "":
                digest = hashlib.sha256(json.dumps([message["role"], content], ensure_ascii=False).encode()).hexdigest()
                identity = f"{position}:{digest}"
            message_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"lyra-import:{conversation_id}:{identity}"))
            extra = message.get("metadata_json", {})
            if isinstance(extra, str):
                extra = json.loads(extra)
            if not isinstance(extra, dict):
                raise ValueError("Message metadata must be an object")
            extra = {**extra, **{key: value for key, value in message.items() if key not in {"role", "content", "text", "model", "tokens", "created_at", "timestamp", "metadata_json"}}}
            prepared.append((legacy_id, message_id, message["role"], content, str(message.get("model") or ""),
                             int(message.get("tokens") or 0), timestamp(message.get("created_at", message.get("timestamp"))),
                             json.dumps(extra, ensure_ascii=False)))
        title = " ".join(str(record.get("title") or "New Conversation").split())[:200]
        created = timestamp(record.get("created_at", record.get("createdAt")))
        conn = self._get_connection()
        with conn:
            # A write lock keeps owner validation and import in one transaction.
            conn.execute("INSERT OR IGNORE INTO users(id,name,preferences_json,created_at,last_seen) VALUES(?, '', '{}', ?, ?)", (user_id, now, now))
            existing = conn.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone()
            if existing and existing["user_id"] != user_id:
                raise PermissionError("Conversation belongs to another user")
            if existing:
                stored_metadata = json.loads(existing["metadata_json"])
                if not isinstance(stored_metadata, dict):
                    raise ValueError("Stored conversation metadata must be an object")
                stored_metadata.update(metadata)
                # Repeated browser migrations cannot overwrite a newer title.
                stored_title = title if existing["title"] == "New Conversation" else existing["title"]
                conn.execute("UPDATE conversations SET title=?, metadata_json=? WHERE id=?", (stored_title, json.dumps(stored_metadata), conversation_id))
            else:
                conn.execute("INSERT INTO conversations(id,user_id,title,summary,created_at,updated_at,metadata_json) VALUES(?, ?, ?, ?, ?, ?, ?)",
                             (conversation_id, user_id, title, str(record.get("summary") or ""), created, now, json.dumps(metadata)))
            inserted = 0
            existing_messages = conn.execute("SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at ASC, rowid ASC", (conversation_id,)).fetchall()
            for position, (legacy_id, message_id, role, content, model, tokens, message_created, extra) in enumerate(prepared):
                if legacy_id:
                    exact = conn.execute("SELECT conversation_id,user_id FROM messages WHERE id=?", (str(legacy_id),)).fetchone()
                    if exact and exact["conversation_id"] == conversation_id and exact["user_id"] == user_id:
                        continue
                elif position < len(existing_messages):
                    candidate = existing_messages[position]
                    if candidate["role"] == role and candidate["content"] == content:
                        merged = {**json.loads(candidate["metadata_json"]), **json.loads(extra)}
                        conn.execute("UPDATE messages SET metadata_json=? WHERE id=?", (json.dumps(merged), candidate["id"]))
                        continue
                inserted += conn.execute("INSERT OR IGNORE INTO messages(id,conversation_id,user_id,role,content,model,tokens,created_at,metadata_json) VALUES(?,?,?,?,?,?,?,?,?)",
                                         (message_id, conversation_id, user_id, role, content, model, tokens, message_created, extra)).rowcount
            if inserted:
                conn.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now, conversation_id))
            stored = dict(conn.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone())
            stored["messages"] = [dict(row) for row in conn.execute("SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at ASC, rowid ASC", (conversation_id,))]
        return stored

    # ── Message Operations ────────────────────────────────────────────

    def add_message(
        self,
        conversation_id: str,
        user_id: str,
        role: str,
        content: str,
        model: str = "",
        tokens: int = 0,
    ) -> dict:
        conn = self._get_connection()
        msg_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        with conn:
            conn.execute(
                "INSERT INTO messages (id, conversation_id, user_id, role, content, model, tokens, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (msg_id, conversation_id, user_id, role, content, model, tokens, now),
            )
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now, conversation_id),
            )
        return {
            "id": msg_id,
            "conversation_id": conversation_id,
            "user_id": user_id,
            "role": role,
            "content": content,
            "model": model,
            "tokens": tokens,
            "created_at": now,
        }

    def get_messages(self, conversation_id: str, limit: int = 100) -> list[dict]:
        conn = self._get_connection()
        rows = conn.execute(
            "SELECT * FROM (SELECT rowid AS message_order, * FROM messages WHERE conversation_id = ? ORDER BY created_at DESC, rowid DESC LIMIT ?) ORDER BY created_at ASC, message_order ASC",
            (conversation_id, max(1, min(int(limit), 10000))),
        ).fetchall()
        return [{key: value for key, value in dict(row).items() if key != 'message_order'} for row in rows]

    def get_task_evidence(self, conversation_id, user_id, exclude_task=None, limit=5):
        """Bounded saved receipts for follow-up analysis, scoped to their owner and chat."""
        rows = self._get_connection().execute(
            'SELECT id,prompt,status,result_json FROM tasks WHERE conversation_id=? AND user_id=? AND id!=? AND result_json IS NOT NULL ORDER BY created_at DESC, rowid DESC LIMIT ?',
            (conversation_id, user_id, exclude_task or '', max(1, min(int(limit), 10)))).fetchall()
        evidence = []
        for row in rows:
            result = json.loads(row['result_json']) or {}
            if result.get('tool_calls'):
                evidence.append({'task_id': row['id'], 'instruction': row['prompt'], 'status': row['status'], 'tool_calls': result['tool_calls']})
        return evidence

    # ── Personal Memory (Consent-Aware) Operations ───────────────────

    def add_memory(self, user_id: str, fact: str, category: str = "preference", consented: bool = True) -> dict:
        conn = self._get_connection()
        self.get_or_create_user(user_id)
        mem_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        with conn:
            conn.execute(
                "INSERT INTO memories (id, user_id, fact, category, consented, is_active, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
                (mem_id, user_id, fact, category, 1 if consented else 0, now, now),
            )
        return {
            "id": mem_id,
            "user_id": user_id,
            "fact": fact,
            "category": category,
            "consented": bool(consented),
            "is_active": True,
            "created_at": now,
            "updated_at": now,
        }

    def get_active_memories(self, user_id: str = "default_user") -> list[dict]:
        conn = self._get_connection()
        rows = conn.execute(
            "SELECT * FROM memories WHERE user_id = ? AND is_active = 1 AND consented = 1 ORDER BY updated_at DESC",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def list_all_memories(self, user_id: str = "default_user") -> list[dict]:
        conn = self._get_connection()
        rows = conn.execute(
            "SELECT * FROM memories WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def update_memory(self, memory_id: str, fact: Optional[str] = None, consented: Optional[bool] = None, is_active: Optional[bool] = None) -> bool:
        conn = self._get_connection()
        now = datetime.utcnow().isoformat()
        updates = []
        params = []
        if fact is not None:
            updates.append("fact = ?")
            params.append(fact)
        if consented is not None:
            updates.append("consented = ?")
            params.append(1 if consented else 0)
        if is_active is not None:
            updates.append("is_active = ?")
            params.append(1 if is_active else 0)
        
        if not updates:
            return False
            
        updates.append("updated_at = ?")
        params.append(now)
        params.append(memory_id)

        with conn:
            res = conn.execute(f"UPDATE memories SET {', '.join(updates)} WHERE id = ?", params)
            return res.rowcount > 0

    def delete_memory(self, memory_id: str) -> bool:
        conn = self._get_connection()
        with conn:
            res = conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            return res.rowcount > 0

    def clear_user_memories(self, user_id: str) -> int:
        conn = self._get_connection()
        with conn:
            res = conn.execute("DELETE FROM memories WHERE user_id = ?", (user_id,))
            return res.rowcount

    # ── Notes & Context Operations ────────────────────────────────────

    def add_note(self, user_id: str, title: str, content: str, tags: str = "", project: str = "") -> dict:
        conn = self._get_connection()
        self.get_or_create_user(user_id)
        note_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        with conn:
            conn.execute(
                "INSERT INTO notes (id, user_id, title, content, tags, project, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (note_id, user_id, title, content, tags, project, now, now),
            )
        return {
            "id": note_id,
            "user_id": user_id,
            "title": title,
            "content": content,
            "tags": tags,
            "project": project,
            "created_at": now,
            "updated_at": now,
        }

    def search_notes(self, user_id: str = "default_user", query: str = "") -> list[dict]:
        conn = self._get_connection()
        if query:
            pattern = f"%{query}%"
            rows = conn.execute(
                "SELECT * FROM notes WHERE user_id = ? AND (title LIKE ? OR content LIKE ? OR tags LIKE ?) ORDER BY updated_at DESC",
                (user_id, pattern, pattern, pattern),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM notes WHERE user_id = ? ORDER BY updated_at DESC",
                (user_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Action Audit Log Operations ───────────────────────────────────

    def log_action(
        self,
        tool: str,
        arguments: dict,
        impact_summary: str,
        approved: bool,
        user_decision: str,
        result_summary: str = "",
        duration_ms: float = 0.0,
    ) -> str:
        conn = self._get_connection()
        audit_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        with conn:
            conn.execute(
                """INSERT INTO action_audit_log 
                   (id, timestamp, tool, arguments_json, impact_summary, approved, user_decision, result_summary, duration_ms) 
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    audit_id,
                    now,
                    tool,
                    json.dumps(arguments),
                    impact_summary,
                    1 if approved else 0,
                    user_decision,
                    result_summary,
                    duration_ms,
                ),
            )
        return audit_id

    def get_audit_log(self, limit: int = 50) -> list[dict]:
        conn = self._get_connection()
        rows = conn.execute(
            "SELECT * FROM action_audit_log ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


# Global database singleton
db = DatabaseManager()
