import logging
import importlib
from typing import Any, Dict, List, Optional


def _get_logger() -> logging.Logger:
    """Return a module-scoped logger."""
    logger = logging.getLogger("DeskmateAI.CommandHandler")
    if not logger.handlers:
        # Assume logging is configured globally via logging.conf; avoid duplicate handlers here.
        logger.propagate = True
    return logger


class CommandHandler:
    """Resolves text commands into actions and executes them.

    Responsibilities:
    - Map natural language commands to actions using mapper
    - Dynamically execute functions from backend.automation modules
    - Log each command execution
    - Provide undo/redo support via services.undo_redo
    - Return structured responses: {status, message, function_executed}
    """

    def __init__(self, user_id: Optional[str] = None) -> None:
        self.logger = _get_logger()
        # Lazy imports to avoid hard failures if modules are stubbed initially
        self._mapper = self._import_mapper()
        self._undo_redo = self._import_undo_redo()
        self._permissions = self._import_permissions()
        self.user_id = user_id or "guest"

    def execute(self, text_command: str) -> Dict[str, Any]:
        """Execute a text command and return a structured response."""
        self.logger.info("Received command: %s", text_command)

        try:
            mapping = self._resolve_command(text_command)
        except Exception as error:  # Resolution failure
            self.logger.exception("Failed to resolve command: %s", text_command)
            return {
                "status": "error",
                "message": f"Failed to resolve command: {error}",
                "function_executed": None,
            }

        try:
            module_name = mapping.get("module")
            function_name = mapping.get("function")
            args: List[Any] = mapping.get("args", [])
            kwargs: Dict[str, Any] = mapping.get("kwargs", {})

            if not module_name or not function_name:
                raise ValueError("Mapping must contain 'module' and 'function'")

            automation_module = self._import_automation_module(module_name)
            if not hasattr(automation_module, function_name):
                raise AttributeError(
                    f"Function '{function_name}' not found in module '{module_name}'"
                )

            target_function = getattr(automation_module, function_name)

            # Enforce permissions if available
            try:
                if self._permissions and hasattr(self._permissions, "enforce_permission"):
                    command_ref = f"{module_name}.{function_name}"
                    self._permissions.enforce_permission(self.user_id, command_ref)
            except Exception:
                self.logger.exception("Permission enforcement failed for %s.%s", module_name, function_name)
                return {
                    "status": "error",
                    "message": "Permission denied",
                    "function_executed": None,
                }
            self.logger.debug(
                "Executing %s.%s with args=%s kwargs=%s",
                module_name,
                function_name,
                args,
                kwargs,
            )

            result = target_function(*args, **kwargs)

            # Record for undo/redo if supported
            self._record_action(module_name, function_name, args, kwargs)

            message = "Command executed successfully"
            self.logger.info("%s -> %s.%s", message, module_name, function_name)
            return {
                "status": "success",
                "message": message,
                "function_executed": f"{module_name}.{function_name}",
                "result": result,
            }
        except Exception as error:
            self.logger.exception(
                "Error executing command mapping for input '%s'", text_command
            )
            return {
                "status": "error",
                "message": str(error),
                "function_executed": None,
            }

    def undo(self) -> Dict[str, Any]:
        """Undo the last action via undo_redo service."""
        try:
            if not self._undo_redo:
                raise RuntimeError("Undo/redo service not available")
            function_path = self._undo_redo.undo_last()
            self.logger.info("Undo executed: %s", function_path)
            return {
                "status": "success",
                "message": "Undo executed",
                "function_executed": function_path,
            }
        except Exception as error:
            self.logger.exception("Undo failed")
            return {"status": "error", "message": str(error), "function_executed": None}

    def redo(self) -> Dict[str, Any]:
        """Redo the last undone action via undo_redo service."""
        try:
            if not self._undo_redo:
                raise RuntimeError("Undo/redo service not available")
            function_path = self._undo_redo.redo_last()
            self.logger.info("Redo executed: %s", function_path)
            return {
                "status": "success",
                "message": "Redo executed",
                "function_executed": function_path,
            }
        except Exception as error:
            self.logger.exception("Redo failed")
            return {"status": "error", "message": str(error), "function_executed": None}

    # Internal helpers

    def _resolve_command(self, text_command: str) -> Dict[str, Any]:
        """Use mapper to resolve text into a mapping dict.

        Expected mapping format:
        {"module": str, "function": str, "args": list, "kwargs": dict}
        """
        if not self._mapper:
            raise RuntimeError("Mapper module not available")

        # Support two common mapper interfaces
        if hasattr(self._mapper, "resolve_command"):
            mapping = self._mapper.resolve_command(text_command)
        elif hasattr(self._mapper, "map"):
            mapping = self._mapper.map(text_command)
        else:
            raise AttributeError("Mapper must expose 'resolve_command' or 'map'")

        if not isinstance(mapping, dict):
            raise TypeError("Mapper must return a dict mapping")
        return mapping

    def _import_automation_module(self, module_name: str):
        """Import automation module by name, preferring backend.automation."""
        try:
            return importlib.import_module(f"backend.automation.{module_name}")
        except ImportError:
            # Fallback if running without package context
            return importlib.import_module(module_name)

    @staticmethod
    def _import_mapper():
        try:
            return importlib.import_module("backend.core.mapper")
        except ImportError:
            try:
                return importlib.import_module("core.mapper")
            except ImportError:
                try:
                    return importlib.import_module("mapper")
                except ImportError:
                    return None

    @staticmethod
    def _import_undo_redo():
        try:
            return importlib.import_module("backend.services.undo_redo")
        except ImportError:
            try:
                return importlib.import_module("services.undo_redo")
            except ImportError:
                try:
                    return importlib.import_module("undo_redo")
                except ImportError:
                    return None

    @staticmethod
    def _import_permissions():
        try:
            return importlib.import_module("backend.security.permissions")
        except ImportError:
            try:
                return importlib.import_module("security.permissions")
            except ImportError:
                try:
                    return importlib.import_module("permissions")
                except ImportError:
                    return None

    def _record_action(
        self,
        module_name: str,
        function_name: str,
        args: List[Any],
        kwargs: Dict[str, Any],
    ) -> None:
        """Record executed action for undo/redo if the service is available."""
        if not self._undo_redo:
            return
        try:
            if hasattr(self._undo_redo, "record_action"):
                self._undo_redo.record_action(
                    function_path=f"{module_name}.{function_name}",
                    args=args,
                    kwargs=kwargs,
                )
        except Exception:
            # Do not fail command execution if recording fails
            self.logger.debug("Failed to record action for undo/redo", exc_info=True)


