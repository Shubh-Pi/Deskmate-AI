import os
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    yaml = None  # type: ignore

from . import logger as project_logger


def _get_logger():
    try:
        return project_logger.get_logger("services.database")
    except Exception:
        import logging

        lg = logging.getLogger("DeskmateAI.services.database")
        if not lg.handlers:
            lg.propagate = True
        return lg


LOGGER = _get_logger()


def _settings_db_path() -> str:
    base = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    settings_path = os.path.join(base, "config", "settings.yaml")
    try:
        if yaml is not None and os.path.exists(settings_path):
            with open(settings_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
                db = (data.get("database") or {}) if isinstance(data, dict) else {}
                path = db.get("path")
                if isinstance(path, str) and path:
                    return os.path.join(base, path) if not os.path.isabs(path) else path
    except Exception:
        LOGGER.debug("Failed to read settings.yaml for DB path", exc_info=True)

    # Fallback: project data/mappings.db
    return os.path.join(base, "data", "mappings.db")


class DatabaseManager:
    """SQLite-backed storage for command mappings and history.

    Tables:
      - mappings(id INTEGER PK, command_text TEXT UNIQUE, action_name TEXT)
      - history(id INTEGER PK, command TEXT, action TEXT, timestamp TEXT)
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path or _settings_db_path()
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    @contextmanager
    def _conn(self):
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            try:
                conn.execute("PRAGMA foreign_keys=ON;")
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS mappings (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  command_text TEXT NOT NULL UNIQUE,
                  action_name TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS history (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  command TEXT NOT NULL,
                  action TEXT NOT NULL,
                  timestamp TEXT NOT NULL
                );
                """
            )

    # Public API

    def add_mapping(self, command_text: str, action_name: str) -> None:
        LOGGER.info("Adding mapping: '%s' -> %s", command_text, action_name)
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO mappings(command_text, action_name) VALUES (?, ?)",
                (command_text, action_name),
            )

    def get_mapping(self, command_text: str) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            cur = conn.execute(
                "SELECT action_name FROM mappings WHERE command_text = ?",
                (command_text,),
            )
            row = cur.fetchone()
            if not row:
                return None
            action_name = row[0]
            # For compatibility with mappers expecting module:function
            mapping: Dict[str, Any] = {"action_name": action_name}
            if ":" in action_name:
                module, function = action_name.split(":", 1)
                mapping.update({"module": module, "function": function, "args": [], "kwargs": {}})
            return mapping

    def list_mappings(self) -> List[Tuple[str, str]]:
        with self._conn() as conn:
            cur = conn.execute("SELECT command_text, action_name FROM mappings ORDER BY command_text ASC")
            return list(cur.fetchall())

    def log_history(self, command: str, action: str) -> None:
        ts = datetime.utcnow().isoformat()
        LOGGER.info("Logging history: %s -> %s", command, action)
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO history(command, action, timestamp) VALUES (?, ?, ?)",
                (command, action, ts),
            )

    def get_history(self, limit: int = 50) -> List[Dict[str, str]]:
        limit = max(1, int(limit))
        with self._conn() as conn:
            cur = conn.execute(
                "SELECT command, action, timestamp FROM history ORDER BY id DESC LIMIT ?",
                (limit,),
            )
            return [
                {"command": r[0], "action": r[1], "timestamp": r[2]}
                for r in cur.fetchall()
            ]

    # Compatibility helpers for existing code paths (optional)

    def upsert_mapping(
        self,
        command: str,
        module: str,
        function: str,
        args: Optional[List[Any]] = None,
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> None:
        action_name = f"{module}:{function}" if module and function else function or module or ""
        self.add_mapping(command, action_name)

    def list_commands(self) -> Iterable[str]:
        return [cmd for (cmd, _) in self.list_mappings()]


# Simple module-level facade to ease imports in other modules
_DEFAULT_DB = DatabaseManager()


def add_mapping(command_text: str, action_name: str) -> None:
    _DEFAULT_DB.add_mapping(command_text, action_name)


def get_mapping(command_text: str) -> Optional[Dict[str, Any]]:
    return _DEFAULT_DB.get_mapping(command_text)


def list_mappings() -> List[Tuple[str, str]]:
    return _DEFAULT_DB.list_mappings()


def log_history(command: str, action: str) -> None:
    _DEFAULT_DB.log_history(command, action)


def get_history(limit: int = 50) -> List[Dict[str, str]]:
    return _DEFAULT_DB.get_history(limit)


# Back-compat exports expected by Learner/Mapper
def upsert_mapping(command: str, module: str, function: str, args=None, kwargs=None) -> None:  # type: ignore[override]
    _DEFAULT_DB.upsert_mapping(command, module, function, args=args, kwargs=kwargs)


def list_commands() -> Iterable[str]:  # type: ignore[override]
    return _DEFAULT_DB.list_commands()


# --------- User utilities (JSON-backed alongside security modules) ---------

def set_user_role(user_id: str, role: str) -> None:
    """Set or update a user's role in data/users.json.

    This mirrors the JSON store used by backend.security.permissions/auth and
    allows admin tools to update roles without touching the security modules.
    """
    try:
        if not isinstance(user_id, str) or not user_id.strip():
            return
        if not isinstance(role, str) or not role.strip():
            return

        base = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        users_path = os.path.join(base, "data", "users.json")
        os.makedirs(os.path.dirname(users_path), exist_ok=True)

        # Read existing users
        users: Dict[str, Any] = {}
        if os.path.exists(users_path):
            try:
                with open(users_path, "r", encoding="utf-8") as f:
                    data = json.load(f) or {}
                    if isinstance(data, dict):
                        users = data
            except Exception:
                LOGGER.debug("Failed to read users.json while setting role", exc_info=True)

        # Update role for the user
        record = users.get(user_id)
        if not isinstance(record, dict):
            record = {}
        record["role"] = role.strip()
        users[user_id] = record

        # Atomic write
        tmp = users_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(users, f, ensure_ascii=False, indent=2)
        os.replace(tmp, users_path)

        LOGGER.info("User role updated: %s -> %s", user_id, role)
    except Exception:
        LOGGER.debug("set_user_role encountered an error", exc_info=True)


