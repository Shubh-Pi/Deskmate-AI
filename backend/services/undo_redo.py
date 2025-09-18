from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from . import logger as project_logger
from . import database as db


def _get_logger():
    try:
        return project_logger.get_logger("services.undo_redo")
    except Exception:
        import logging

        lg = logging.getLogger("DeskmateAI.services.undo_redo")
        if not lg.handlers:
            lg.propagate = True
        return lg


LOGGER = _get_logger()


@dataclass
class ActionRecord:
    function_path: str
    args: List[Any]
    kwargs: Dict[str, Any]
    reversible: bool = False
    undo_function_path: Optional[str] = None


class UndoRedoManager:
    """Manage undo/redo stacks for executed actions.

    Notes:
    - Not all actions are reversible. For non-reversible actions, undo() will report gracefully.
    - On record, the executed action is pushed to the executed stack and history is logged in DB.
    - undo() moves the action to the undone stack; if reversible and undo function available, it's executed.
    - redo() re-executes the original action from the undone stack and moves it back to executed.
    """

    def __init__(self) -> None:
        self._executed_stack: List[ActionRecord] = []
        self._undone_stack: List[ActionRecord] = []

    # Public API

    def record_action(
        self,
        function_path: str,
        args: Optional[List[Any]] = None,
        kwargs: Optional[Dict[str, Any]] = None,
        *,
        reversible: bool = False,
        undo_function_path: Optional[str] = None,
    ) -> None:
        record = ActionRecord(
            function_path=function_path,
            args=list(args or []),
            kwargs=dict(kwargs or {}),
            reversible=reversible,
            undo_function_path=undo_function_path,
        )
        self._executed_stack.append(record)
        self._undone_stack.clear()
        try:
            db.log_history(command=function_path, action="EXECUTE")
        except Exception:
            LOGGER.debug("Failed to log history for record_action", exc_info=True)

    def undo_last(self) -> Dict[str, Any]:
        if not self._executed_stack:
            return {"status": "error", "message": "Nothing to undo"}

        record = self._executed_stack.pop()
        self._undone_stack.append(record)

        try:
            db.log_history(command=record.function_path, action="UNDO")
        except Exception:
            LOGGER.debug("Failed to log history for undo", exc_info=True)

        if not record.reversible or not record.undo_function_path:
            msg = "Action is not reversible"
            LOGGER.info("Undo requested for non-reversible action: %s", record.function_path)
            return {"status": "error", "message": msg, "function_executed": None}

        try:
            undo_fn = self._import_function(record.undo_function_path)
            if not undo_fn:
                raise RuntimeError("Undo function not found")
            undo_fn(*record.args, **record.kwargs)
            LOGGER.info("Undid action via %s", record.undo_function_path)
            return {
                "status": "success",
                "message": "Undo executed",
                "function_executed": record.undo_function_path,
            }
        except Exception as error:
            LOGGER.exception("Undo execution failed for %s", record.undo_function_path)
            return {"status": "error", "message": str(error), "function_executed": None}

    def redo_last(self) -> Dict[str, Any]:
        if not self._undone_stack:
            return {"status": "error", "message": "Nothing to redo"}

        record = self._undone_stack.pop()
        self._executed_stack.append(record)

        try:
            db.log_history(command=record.function_path, action="REDO")
        except Exception:
            LOGGER.debug("Failed to log history for redo", exc_info=True)

        try:
            redo_fn = self._import_function(record.function_path)
            if not redo_fn:
                raise RuntimeError("Function not found for redo")
            redo_fn(*record.args, **record.kwargs)
            LOGGER.info("Redid action via %s", record.function_path)
            return {
                "status": "success",
                "message": "Redo executed",
                "function_executed": record.function_path,
            }
        except Exception as error:
            LOGGER.exception("Redo execution failed for %s", record.function_path)
            return {"status": "error", "message": str(error), "function_executed": None}

    # Utilities

    @staticmethod
    def _import_function(function_path: str):
        if not function_path or "." not in function_path:
            return None
        module_name, func_name = function_path.rsplit(".", 1)
        try:
            module = importlib.import_module(module_name)
            return getattr(module, func_name, None)
        except Exception:
            return None


# Module-level singleton and simple facade for ease of use
_MANAGER = UndoRedoManager()


def record_action(function_path: str, args=None, kwargs=None, *, reversible: bool = False, undo_function_path: Optional[str] = None) -> None:
    _MANAGER.record_action(
        function_path=function_path,
        args=args,
        kwargs=kwargs,
        reversible=reversible,
        undo_function_path=undo_function_path,
    )


def undo_last() -> Dict[str, Any]:
    return _MANAGER.undo_last()


def redo_last() -> Dict[str, Any]:
    return _MANAGER.redo_last()


