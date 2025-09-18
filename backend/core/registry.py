import importlib
import inspect
import logging
import pkgutil
from typing import Any, Callable, Dict, List, Optional, Tuple


def _get_logger() -> logging.Logger:
    logger = logging.getLogger("DeskmateAI.CommandRegistry")
    if not logger.handlers:
        logger.propagate = True
    return logger


class CommandRegistry:
    """Discovers and registers automation functions for dynamic lookup.

    By default, discovers callables in modules under backend.automation.* that are not private
    (no leading underscore) and are plain functions. New automation modules are discovered at
    runtime via pkgutil; no core code changes required to register new functions.
    """

    def __init__(self) -> None:
        self.logger = _get_logger()
        self._registry: Dict[str, Dict[str, Any]] = {}
        self._discover_modules_and_functions()

    # Public API

    def get_function(self, action_name: str) -> Optional[Callable[..., Any]]:
        entry = self._registry.get(action_name)
        if not entry:
            return None
        module = self._import_module(entry["module_path"]) if isinstance(entry, dict) else None
        if not module:
            return None
        func_name = entry.get("function_name")
        return getattr(module, func_name, None)

    def list_commands(self) -> List[str]:
        return sorted(list(self._registry.keys()))

    def get_registry(self) -> Dict[str, Dict[str, Any]]:
        return dict(self._registry)

    # Discovery

    def _discover_modules_and_functions(self) -> None:
        package_name = "backend.automation"
        try:
            package = importlib.import_module(package_name)
        except ImportError:
            self.logger.debug("Unable to import %s", package_name, exc_info=True)
            return

        for module_info in pkgutil.iter_modules(package.__path__, package.__name__ + "."):
            module_name = module_info.name
            try:
                module = importlib.import_module(module_name)
            except Exception:
                self.logger.debug("Failed to import automation module %s", module_name, exc_info=True)
                continue

            self._register_module_functions(module_name, module)

    def _register_module_functions(self, module_path: str, module: Any) -> None:
        for name, obj in inspect.getmembers(module, inspect.isfunction):
            if name.startswith("_"):
                continue

            action_key = f"{module_path.split('.')[-1]}:{name}"
            self._registry[action_key] = {
                "module_path": module_path,
                "function_name": name,
            }
            self.logger.debug("Registered action: %s -> %s.%s", action_key, module_path, name)

    @staticmethod
    def _import_module(module_path: str):
        try:
            return importlib.import_module(module_path)
        except ImportError:
            return None


