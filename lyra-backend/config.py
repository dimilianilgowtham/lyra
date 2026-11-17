"""
LYRA Backend — Configuration
Loads server-side configuration and API keys securely.
"""

import os
import secrets
from pathlib import Path
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = Path(__file__).resolve().parent

# Installed apps keep user configuration outside their immutable resources.
# Process environment values always win; legacy development files remain a fallback.
CONFIG_DIR = Path(os.getenv("LYRA_CONFIG_DIR", str(BACKEND_DIR))).expanduser().resolve()
ENV_FILE = Path(os.getenv("LYRA_ENV_FILE", str(CONFIG_DIR / ".env"))).expanduser().resolve()
load_dotenv(ENV_FILE)
load_dotenv(BACKEND_DIR / ".env")
load_dotenv(ROOT_DIR / ".env")
DATA_DIR = Path(os.getenv("LYRA_DATA_DIR") or BACKEND_DIR / "data").expanduser().resolve()


def _database_path() -> str:
    configured = os.getenv("DATABASE_PATH")
    if not configured:
        return str(DATA_DIR / "lyra.db")
    path = Path(configured).expanduser()
    # Historical .env files use lyra-backend/data/lyra.db. Resolve relative
    # paths from the project root rather than the desktop app's arbitrary cwd.
    return str((path if path.is_absolute() else ROOT_DIR / path).resolve())


def _legacy_session_file() -> str:
    configured = os.getenv("LYRA_LEGACY_SESSION_FILE")
    if configured:
        return str(Path(configured).expanduser().resolve())
    return str(DATA_DIR / "session_memory.json")


def _get_secret(primary: str, fallback_prefix: str = "VITE_") -> str:
    """Get secret key, checking standard server-side var first, then legacy VITE_ prefixed var."""
    val = os.getenv(primary)
    if val:
        return val.strip()
    val = os.getenv(f"{fallback_prefix}{primary}")
    return val.strip() if val else ""


def _local_session_token() -> str:
    configured = os.getenv("BACKEND_AUTH_TOKEN")
    if configured:
        return configured
    token_file = DATA_DIR / ".backend-auth-token"
    token_file.parent.mkdir(parents=True, exist_ok=True)
    if token_file.is_symlink():
        raise RuntimeError("Backend token file must not be a symbolic link")
    try:
        token = token_file.read_text().strip()
        if len(token) >= 32:
            token_file.chmod(0o600)
            return token
    except FileNotFoundError:
        pass
    token = secrets.token_urlsafe(32)
    token_file.write_text(token)
    token_file.chmod(0o600)
    return token


class Settings:
    # LLM Providers (server-side authoritative)
    ANTHROPIC_API_KEY: str = _get_secret("ANTHROPIC_API_KEY")
    GROQ_API_KEY: str = _get_secret("GROQ_API_KEY")
    GEMINI_API_KEY: str = _get_secret("GEMINI_API_KEY")
    OPENAI_API_KEY: str = _get_secret("OPENAI_API_KEY")
    NVIDIA_API_KEY: str = _get_secret("NVIDIA_API_KEY")
    OPENROUTER_API_KEY: str = _get_secret("OPENROUTER_API_KEY")
    HF_TOKEN: str = _get_secret("HF_TOKEN")

    # Claude Code CLI
    CLAUDE_BINARY_PATH: str = os.getenv("CLAUDE_BINARY_PATH", "/Users/anilgowtham/.local/bin/claude")

    # Local LLM Adapter
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    DEFAULT_LOCAL_MODEL: str = os.getenv("DEFAULT_LOCAL_MODEL", "llama3.2")
    DEFAULT_CLOUD_MODEL: str = os.getenv("DEFAULT_CLOUD_MODEL", "llama-3.3-70b-versatile")

    # Server
    HOST: str = os.getenv("BACKEND_HOST", "127.0.0.1")
    if HOST not in ("127.0.0.1", "localhost", "::1"):
        HOST = "127.0.0.1"
    PORT: int = int(os.getenv("BACKEND_PORT", "8100"))
    BACKEND_AUTH_TOKEN: str = _local_session_token()
    ALLOWED_ORIGINS: tuple[str, ...] = (
        "http://127.0.0.1:3000", "http://localhost:3000",
        "http://127.0.0.1:5173", "http://localhost:5173",
    )
    WORKSPACE_ROOTS: tuple[Path, ...] = tuple(
        Path(root).expanduser().resolve()
        for root in os.getenv("LYRA_WORKSPACE_ROOTS", os.pathsep.join([
            str(ROOT_DIR), str(Path.home() / "Desktop"),
            str(Path.home() / "Documents"), str(Path.home() / "Downloads"),
        ])).split(os.pathsep) if root
    )

    # Voice
    TTS_VOICE: str = os.getenv("TTS_VOICE", "Samantha")
    TTS_RATE: int = int(os.getenv("TTS_RATE", "185"))

    # Storage & Persistence
    CONFIG_DIR: str = str(CONFIG_DIR)
    ENV_FILE: str = str(ENV_FILE)
    DATA_DIR: str = str(DATA_DIR)
    DB_PATH: str = _database_path()
    LEGACY_SESSION_FILE: str = _legacy_session_file()


settings = Settings()
