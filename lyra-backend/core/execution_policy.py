"""Workspace policy and explicit execution consent; this is not an OS sandbox."""

from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Iterable


class PolicyError(ValueError):
    pass


_execution_consent = ContextVar("lyra_execution_consent", default=False)
_execution_roots = ContextVar("lyra_execution_roots", default=None)


@contextmanager
def approved_tool_context(approved: bool, *, policy=None):
    roots_token = _execution_roots.set(policy.roots) if policy is not None else None
    token = _execution_consent.set(approved)
    try:
        yield
    finally:
        _execution_consent.reset(token)
        if roots_token is not None:
            _execution_roots.reset(roots_token)


def has_execution_consent() -> bool:
    return _execution_consent.get()


class ExecutionPolicy:
    """Canonical containment for file APIs. Shell processes are not isolated."""

    SECRET_DIRS = frozenset({".ssh", ".aws", ".azure", ".gnupg", ".kube", ".codex", ".config", ".git"})
    SECRET_NAMES = frozenset({".backend-auth-token", "id_rsa", "id_ed25519", "id_dsa", ".npmrc", ".pypirc", "credentials", "credentials.json", "service-account.json"})
    SECRET_SUFFIXES = frozenset({".pem", ".key", ".p12", ".pfx", ".keystore"})
    MUTATIONS = frozenset({"execute_command", "write_file", "create_folder", "run_claude_code", "set_clipboard", "send_notification", "open_app", "close_app", "open_url", "set_volume", "mute_volume", "unmute_volume", "toggle_dark_mode", "type_text", "press_hotkey", "lock_screen", "create_reminder", "complete_reminder", "delete_reminder", "remember", "forget", "save_memory", "delete_memory"})
    PRIVATE_READS = frozenset({"take_screenshot", "get_clipboard"})

    def __init__(self, roots: Iterable[Path | str] | None = None):
        self._explicit_roots = tuple(roots) if roots is not None else None

    @property
    def roots(self) -> tuple[Path, ...]:
        if self._explicit_roots is not None:
            raw = self._explicit_roots
        else:
            from config import settings, ROOT_DIR
            raw = _execution_roots.get()
            if raw is None:
                raw = getattr(settings, "WORKSPACE_ROOTS", (ROOT_DIR, Path.home() / "Desktop", Path.home() / "Documents", Path.home() / "Downloads"))
        return tuple(Path(root).expanduser().resolve() for root in raw)

    @property
    def default_root(self) -> Path:
        if not self.roots:
            raise PolicyError("No workspace roots are configured.")
        return self.roots[0]

    def resolve_path(self, raw: Path | str, *, allow_sensitive: bool = False) -> Path:
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = self.default_root / path
        if not allow_sensitive and self.is_sensitive(path):
            raise PolicyError("Access to secrets, credentials, or private-key paths is denied.")
        path = path.resolve()
        if not any(path == root or root in path.parents for root in self.roots):
            raise PolicyError("Path is outside configured workspace roots.")
        if not allow_sensitive and self.is_sensitive(path):
            raise PolicyError("Access to secrets, credentials, or private-key paths is denied.")
        return path

    @classmethod
    def is_sensitive(cls, path: Path) -> bool:
        parts = {part.lower() for part in path.parts}
        name = path.name.lower()
        return bool(parts & cls.SECRET_DIRS or name in cls.SECRET_NAMES or name.startswith(".env") or path.suffix.lower() in cls.SECRET_SUFFIXES)

    def requires_approval(self, tool_name: str, declared: bool = False) -> bool:
        return declared or tool_name in self.MUTATIONS or tool_name in self.PRIVATE_READS

    def validate_tool_paths(self, tool_name: str, args: dict) -> None:
        path_keys = {"read_file": "filepath", "write_file": "filepath", "list_directory": "dirpath", "search_files": "search_path", "execute_command": "cwd", "run_claude_code": "cwd", "create_folder": "base_path"}
        key = path_keys.get(tool_name)
        if key:
            path = self.resolve_path(args.get(key) or self.default_root)
            if tool_name == "create_folder":
                name = args.get("folder_name", "")
                if not name or name in {".", ".."} or Path(name).name != name:
                    raise PolicyError("Folder name must be one path component.")
                self.resolve_path(path / name)
        if tool_name == "open_url":
            from urllib.parse import urlsplit
            if urlsplit(args.get("url", "")).scheme.lower() not in {"https", "http"}:
                raise PolicyError("Only http and https URLs may be opened.")


def validate_arguments(schema: dict, value, path: str = "arguments") -> None:
    """Small JSON-schema validator for tool types, required fields and bounds."""
    expected = schema.get("type")
    predicates = {"object": lambda v: isinstance(v, dict), "array": lambda v: isinstance(v, list), "string": lambda v: isinstance(v, str), "boolean": lambda v: isinstance(v, bool), "integer": lambda v: isinstance(v, int) and not isinstance(v, bool), "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool), "null": lambda v: v is None}
    if expected in predicates and not predicates[expected](value):
        raise ValueError(f"{path} must be {expected}.")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path} is not an allowed value.")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        missing = [key for key in schema.get("required", []) if key not in value]
        if missing:
            raise ValueError(f"{path} is missing required fields: {', '.join(missing)}.")
        if schema.get("additionalProperties", False) is False:
            unknown = set(value) - set(properties)
            if unknown:
                raise ValueError(f"Unexpected {path} fields: {', '.join(sorted(unknown))}.")
        for key, item in value.items():
            if key in properties:
                validate_arguments(properties[key], item, f"{path}.{key}")
    if isinstance(value, list):
        for index, item in enumerate(value):
            validate_arguments(schema.get("items", {}), item, f"{path}[{index}]")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise ValueError(f"{path} is below the minimum.")
        if "maximum" in schema and value > schema["maximum"]:
            raise ValueError(f"{path} is above the maximum.")
    if isinstance(value, str) and len(value) > schema.get("maxLength", 1_000_000):
        raise ValueError(f"{path} exceeds the length limit.")
