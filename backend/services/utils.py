import importlib
import re
from datetime import datetime, timezone
from typing import Any, Optional


def normalize_text(text: Optional[str]) -> str:
    """Normalize user input: trim, collapse whitespace, lowercase."""
    if not text:
        return ""
    cleaned = re.sub(r"\s+", " ", str(text)).strip()
    return cleaned.lower()


def timestamp() -> str:
    """Return an ISO-8601 UTC timestamp string."""
    return datetime.now(timezone.utc).isoformat()


def confirm_action(prompt: str, default: bool = False) -> bool:
    """Ask for Y/N confirmation in CLI contexts. Returns default on failure.

    This is safe for non-interactive contexts: if input() fails, default is returned.
    """
    try:
        answer = input(f"{prompt} [y/N]: ").strip().lower()
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        return default
    except Exception:
        return default


def safe_import(module: str) -> Optional[Any]:
    """Attempt to import a module by name; return None if unavailable."""
    try:
        return importlib.import_module(module)
    except Exception:
        return None


# Additional lightweight helpers used across the backend

def ensure_list(value: Any) -> list:
    """Coerce value to a list: None -> [], list -> itself, other -> [value]."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def clamp_int(value: Any, minimum: int, maximum: int) -> int:
    """Convert to int and clamp to a range."""
    try:
        num = int(value)
    except Exception:
        num = minimum
    return max(minimum, min(maximum, num))


