"""Keep provider credentials out of logs, task results, and error messages."""
import re
from config import settings


def safe_error(error) -> str:
    text = str(error)
    for name in dir(settings):
        if name.endswith("_API_KEY") or name in ("BACKEND_AUTH_TOKEN", "HF_TOKEN"):
            secret = getattr(settings, name, "")
            if isinstance(secret, str) and secret:
                text = text.replace(secret, "[redacted]")
    text = re.sub(r"(?i)([?&](?:key|token|access_token)=)[^&\s]+", r"\1[redacted]", text)
    return text[:1000]
