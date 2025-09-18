import json
import logging
import os
from collections import deque
from typing import Any, Deque, Dict, List, Optional


def _get_logger() -> logging.Logger:
    logger = logging.getLogger("DeskmateAI.Memory")
    if not logger.handlers:
        logger.propagate = True
    return logger


class Memory:
    """Short-term and long-term memory for command history and context.

    - Short-term memory: in-memory deque of recent commands for the current session
    - Long-term memory: persisted json file capturing executed commands across sessions
    - Integrates with undo/redo by recording actions and providing history traversal
    """

    def __init__(self, max_short_term: int = 50, store_path: Optional[str] = None) -> None:
        self.logger = _get_logger()
        self.max_short_term = max_short_term
        self.short_term: Deque[Dict[str, Any]] = deque(maxlen=max_short_term)
        self.store_path = store_path or self._default_store_path()
        self._ensure_store_directory()
        self._load_long_term()

        self._undo_redo = self._import_undo_redo()

    # Public API

    def remember(self, record: Dict[str, Any]) -> None:
        """Record a command execution in short and long-term memory.

        Expected record keys: {"command", "function", "result", "timestamp"}
        """
        self.short_term.append(record)
        self._append_long_term(record)
        self._record_undo_redo(record)

    def recall(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Return the most recent commands from short-term memory."""
        if limit <= 0:
            return []
        items = list(self.short_term)[-limit:]
        return items[::-1]

    def forget(self, count: int = 1) -> List[Dict[str, Any]]:
        """Remove the most recent N records from short-term and long-term memory."""
        if count <= 0:
            return []

        removed: List[Dict[str, Any]] = []
        for _ in range(min(count, len(self.short_term))):
            removed.append(self.short_term.pop())

        if removed:
            self._remove_from_long_term(len(removed))
        return removed

    # Internal helpers

    def _default_store_path(self) -> str:
        base = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "data",
        )
        return os.path.join(base, "memory.json")

    def _ensure_store_directory(self) -> None:
        directory = os.path.dirname(self.store_path)
        os.makedirs(directory, exist_ok=True)

    def _load_long_term(self) -> None:
        try:
            if os.path.exists(self.store_path):
                with open(self.store_path, "r", encoding="utf-8") as file:
                    data = json.load(file)
                    if isinstance(data, list):
                        for item in data[-self.max_short_term :]:
                            if isinstance(item, dict):
                                self.short_term.append(item)
        except Exception:
            self.logger.debug("Failed to load long-term memory", exc_info=True)

    def _append_long_term(self, record: Dict[str, Any]) -> None:
        try:
            history: List[Dict[str, Any]] = []
            if os.path.exists(self.store_path):
                with open(self.store_path, "r", encoding="utf-8") as file:
                    loaded = json.load(file)
                    if isinstance(loaded, list):
                        history = loaded
            history.append(record)
            with open(self.store_path, "w", encoding="utf-8") as file:
                json.dump(history, file, ensure_ascii=False, indent=2)
        except Exception:
            self.logger.debug("Failed to append long-term memory", exc_info=True)

    def _remove_from_long_term(self, count: int) -> None:
        try:
            history: List[Dict[str, Any]] = []
            if os.path.exists(self.store_path):
                with open(self.store_path, "r", encoding="utf-8") as file:
                    loaded = json.load(file)
                    if isinstance(loaded, list):
                        history = loaded
            # Remove last N items
            if count > 0 and history:
                history = history[: max(0, len(history) - count)]
            with open(self.store_path, "w", encoding="utf-8") as file:
                json.dump(history, file, ensure_ascii=False, indent=2)
        except Exception:
            self.logger.debug("Failed to remove from long-term memory", exc_info=True)

    def _record_undo_redo(self, record: Dict[str, Any]) -> None:
        if not self._undo_redo:
            return
        try:
            if hasattr(self._undo_redo, "record_action"):
                self._undo_redo.record_action(
                    function_path=record.get("function"),
                    args=record.get("args", []),
                    kwargs=record.get("kwargs", {}),
                )
        except Exception:
            self.logger.debug("Failed to record undo/redo action", exc_info=True)

    @staticmethod
    def _import_undo_redo():
        try:
            return __import__("backend.services.undo_redo", fromlist=["*"])
        except ImportError:
            try:
                return __import__("services.undo_redo", fromlist=["*"])
            except ImportError:
                try:
                    return __import__("undo_redo", fromlist=["*"])
                except ImportError:
                    return None


