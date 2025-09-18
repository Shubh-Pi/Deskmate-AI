import json
import logging
import os
import importlib
import inspect
from typing import Any, Callable, Dict, List, Optional, Tuple


def _get_logger() -> logging.Logger:
    logger = logging.getLogger("DeskmateAI.Learner")
    if not logger.handlers:
        logger.propagate = True
    return logger


class Learner:
    """Learns new command-to-action mappings and persists them.

    Workflow for unknown commands:
    1) Try to suggest an intended action via fuzzy matching against entries in config/commands.json
    2) Ask the user to confirm the suggestion via provided callbacks
    3) If confirmed, attempt to map to a concrete automation function via registry (if available)
    4) If not confirmed or registry mapping missing, ask user to manually map to an existing action
    5) Persist the new mapping using services.database so it survives restarts

    This class is UI-agnostic. It relies on callbacks for user interaction.

    confirm_callback: Callable[[str], bool]
        Called with the suggested action key (e.g., "open_browser"). Should return True/False.

    manual_map_callback: Callable[[str, List[str]], Dict[str, Any]]
        Called when auto suggestion is rejected or insufficient. Should return a mapping dict:
        {"module": str, "function": str, "args": list, "kwargs": dict}
    """

    def __init__(
        self,
        confirm_callback: Callable[[str], bool],
        manual_map_callback: Callable[[str, List[str]], Dict[str, Any]],
        commands_config_path: Optional[str] = None,
    ) -> None:
        self.logger = _get_logger()
        self.confirm_callback = confirm_callback
        self.manual_map_callback = manual_map_callback
        self.commands_config_path = commands_config_path or self._default_commands_path()
        # Initialize registry directly (no private import helpers)
        try:
            from backend.core.registry import CommandRegistry  # type: ignore

            self._registry = CommandRegistry()
        except Exception:
            self._registry = None  # type: ignore
        self._db = self._import_database()

        self._commands_index = self._load_commands_index(self.commands_config_path)

    # Public API

    def handle_unknown(self, text_command: str) -> Dict[str, Any]:
        self.logger.info("Learning mapping for unknown command: %s", text_command)

        suggested_action = self._suggest_action(text_command)
        chosen_mapping: Optional[Dict[str, Any]] = None
        mapping_source = "manual"

        if suggested_action:
            self.logger.debug("Suggested action: %s", suggested_action)
            try:
                if self.confirm_callback(suggested_action):
                    mapping = self._map_action_via_registry(suggested_action)
                    if mapping:
                        chosen_mapping = mapping
                        mapping_source = "auto"
                    else:
                        self.logger.debug(
                            "Registry has no mapping for '%s'; falling back to manual map",
                            suggested_action,
                        )
            except Exception:
                self.logger.debug("Confirmation callback failed", exc_info=True)

        if not chosen_mapping:
            # Prefer enhanced interactive mapping; fall back to provided manual_map_callback
            available_actions = self._list_registry_actions()
            chosen_mapping = self._interactive_manual_map(text_command, available_actions)
            if not chosen_mapping or not isinstance(chosen_mapping, dict) or not chosen_mapping.get("module"):
                try:
                    chosen_mapping = self.manual_map_callback(text_command, available_actions)
                except Exception:
                    chosen_mapping = {"module": "", "function": "", "args": [], "kwargs": {}}

        # Validate mapping shape
        self._validate_mapping(chosen_mapping)

        # Persist mapping
        self._persist_mapping(text_command, chosen_mapping)

        self.logger.info(
            "Saved mapping for '%s' -> %s.%s",
            text_command,
            chosen_mapping["module"],
            chosen_mapping["function"],
        )
        return {
            "status": "success",
            "message": "New command mapping saved",
            "function_executed": f"{chosen_mapping['module']}.{chosen_mapping['function']}",
            "source": mapping_source,
        }

    # Internal helpers

    def _suggest_action(self, text_command: str) -> Optional[str]:
        try:
            from fuzzywuzzy import fuzz
        except Exception:
            # If fuzzy matching isn't available, skip suggestion
            return None

        best_key: Optional[str] = None
        best_score = 0
        for action_key, synonyms in self._commands_index.items():
            candidates = [action_key] + list(synonyms)
            score = max(fuzz.token_set_ratio(text_command, c) for c in candidates)
            if score > best_score:
                best_key, best_score = action_key, score

        # Heuristic threshold
        return best_key if best_score >= 70 else None

    def _map_action_via_registry(self, action_key: str) -> Optional[Dict[str, Any]]:
        if not self._registry:
            return None

        # Support either a dict REGISTRY or a function get_registry()
        try:
            if hasattr(self._registry, "get_registry"):
                registry: Dict[str, Dict[str, Any]] = self._registry.get_registry()
            elif hasattr(self._registry, "REGISTRY"):
                registry = getattr(self._registry, "REGISTRY")
            else:
                return None
        except Exception:
            return None

        entry = registry.get(action_key)
        if not entry or not isinstance(entry, dict):
            return None

        module: Optional[str] = None
        function: Optional[str] = None
        if "module_path" in entry and "function_name" in entry:
            module = str(entry.get("module_path", "")).split(".")[-1]
            function = str(entry.get("function_name"))
        else:
            module = entry.get("module")
            function = entry.get("function")

        if not module or not function:
            return None

        mapping = {
            "module": module,
            "function": function,
            "args": [],
            "kwargs": {},
        }
        try:
            self._validate_mapping(mapping)
        except Exception:
            return None
        return mapping

    def _persist_mapping(self, text_command: str, mapping: Dict[str, Any]) -> None:
        if not self._db:
            raise RuntimeError(
                "Database service not available. Cannot persist new mapping."
            )

        # Support either a Database class instance with upsert_mapping or a module-level function
        if hasattr(self._db, "Database"):
            db = self._db.Database()
            if hasattr(db, "upsert_mapping"):
                db.upsert_mapping(
                    command=text_command,
                    module=mapping["module"],
                    function=mapping["function"],
                    args=mapping.get("args", []),
                    kwargs=mapping.get("kwargs", {}),
                )
                return

        if hasattr(self._db, "upsert_mapping"):
            self._db.upsert_mapping(
                command=text_command,
                module=mapping["module"],
                function=mapping["function"],
                args=mapping.get("args", []),
                kwargs=mapping.get("kwargs", {}),
            )
            return

        raise RuntimeError("Database service must expose upsert_mapping()")

    # ---------------- Enhanced interactive/manual mapping flow ----------------

    def _list_registry_actions(self) -> List[str]:
        """Return available action keys like 'module:function' discovered by registry or config."""
        try:
            if hasattr(self._registry, "get_registry"):
                reg: Dict[str, Dict[str, Any]] = self._registry.get_registry()
                return sorted(list(reg.keys()))
        except Exception:
            pass
        return sorted(list(self._commands_index.keys()))

    @staticmethod
    def _print_box(lines: List[str]) -> None:
        sep = "\n" + ("\u2500" * 31) + "\n"  # ────────────────────────────────
        msg = sep + "\n".join(lines) + sep
        try:
            from backend.services import logger as project_logger  # type: ignore

            project_logger.info("{}", msg)
        except Exception:
            try:
                print(msg)
            except Exception:
                pass

    def _prompt_module_choice(self, actions: List[str]) -> Optional[str]:
        modules = sorted({a.split(":")[0] for a in actions if ":" in a})
        if not modules:
            return None
        while True:
            try:
                self._print_box([
                    "Select a module (e.g., apps, browser, system, youtube, whatsapp, email):",
                    ", ".join(modules),
                ])
                choice = input("Module> ").strip().lower()
            except Exception:
                return None
            if choice in modules:
                return choice
            try:
                from backend.services import logger as project_logger  # type: ignore

                project_logger.info("Invalid module: {}", choice)
            except Exception:
                pass

    def _list_module_functions(self, module_name: str) -> List[str]:
        candidates = [f"backend.automation.{module_name}", module_name]
        module = None
        for path in candidates:
            try:
                module = importlib.import_module(path)
                break
            except Exception:
                continue
        if module is None:
            return []
        return sorted([name for name, obj in inspect.getmembers(module, inspect.isfunction) if not name.startswith("_")])

    def _prompt_function_choice(self, module_name: str) -> Optional[str]:
        functions = self._list_module_functions(module_name)
        if not functions:
            return None
        lines = [f"Available functions in {module_name}:"]
        lines.extend([f"[{i+1}] {fn}" for i, fn in enumerate(functions)])
        self._print_box(lines)
        while True:
            try:
                raw = input("Enter function number: ").strip()
                idx = int(raw) - 1
                if 0 <= idx < len(functions):
                    return functions[idx]
            except Exception:
                pass
            try:
                from backend.services import logger as project_logger  # type: ignore

                project_logger.info("Invalid selection. Please try again.")
            except Exception:
                pass

    def _interactive_manual_map(self, text_command: str, available_actions: List[str]) -> Dict[str, Any]:
        # Pretty header and suggestions
        lines = [
            f"❓ Unknown Command: \"{text_command}\"",
            "Suggested Actions (from registry + automation modules):",
        ]
        for action in available_actions:
            lines.append(f"- {action}")
        self._print_box(lines)

        module = self._prompt_module_choice(available_actions)
        if not module:
            return {"module": "", "function": "", "args": [], "kwargs": {}}

        function = self._prompt_function_choice(module)
        if not function:
            return {"module": "", "function": "", "args": [], "kwargs": {}}

        # Confirmation message
        self._print_box([
            "✅ Mapping saved:",
            f"\"{text_command}\" → {module}.{function}",
        ])
        return {"module": module, "function": function, "args": [], "kwargs": {}}


# ---------------- Module-level utilities ----------------

def clear_command_mapping(command: str) -> None:
    """Delete a stored mapping for the given command text from the database.

    This is a safe, targeted removal that does not affect other mappings.
    Logs the deletion and prints a confirmation box. No exception is raised outward.
    """
    try:
        from backend.services import logger as project_logger  # type: ignore
    except Exception:
        project_logger = None  # type: ignore

    try:
        if not isinstance(command, str) or not command.strip():
            # Nothing to do; show friendly message
            try:
                Learner._print_box(["No command provided. Nothing to clear."])
            except Exception:
                pass
            return

        normalized = command.strip()

        # Import database service and resolve DB path consistently with the app
        try:
            import backend.services.database as db  # type: ignore
        except Exception:
            db = None  # type: ignore

        if db is None:
            try:
                Learner._print_box([f"Could not access database service to clear: \"{normalized}\""])
            except Exception:
                pass
            return

        # Check if mapping exists first (use the module-level facade if available)
        exists = None
        try:
            if hasattr(db, "get_mapping"):
                exists = db.get_mapping(normalized)
            elif hasattr(db, "DatabaseManager"):
                _mgr = db.DatabaseManager()
                exists = _mgr.get_mapping(normalized)
        except Exception:
            exists = None

        # Perform deletion directly against the mappings table using DatabaseManager
        try:
            manager = db.DatabaseManager()
            with manager._conn() as conn:  # type: ignore[attr-defined]
                conn.execute("DELETE FROM mappings WHERE command_text = ?", (normalized,))
        except Exception:
            try:
                Learner._print_box([f"Failed to clear mapping for command: \"{normalized}\""])
            except Exception:
                pass
            return

        # Log and print outcome
        try:
            if project_logger is not None:
                if exists:
                    project_logger.info("Cleared mapping for command: {}", normalized)
                else:
                    project_logger.info("No existing mapping to clear for command: {}", normalized)
        except Exception:
            pass

        try:
            if exists:
                Learner._print_box([
                    f"✅ Mapping for command \"{normalized}\" cleared successfully.",
                ])
            else:
                Learner._print_box([
                    f"No existing mapping found for command \"{normalized}\".",
                ])
        except Exception:
            pass
    except Exception:
        # Swallow any unexpected error to avoid breaking flows
        try:
            Learner._print_box(["An unexpected error occurred while clearing the mapping."])
        except Exception:
            pass

    @staticmethod
    def _validate_mapping(mapping: Dict[str, Any]) -> None:
        if not isinstance(mapping, dict):
            raise TypeError("Mapping must be a dict")
        for key in ("module", "function"):
            if key not in mapping or not isinstance(mapping[key], str) or not mapping[key]:
                raise ValueError(f"Mapping must contain non-empty '{key}'")
        if "args" in mapping and not isinstance(mapping["args"], list):
            raise TypeError("'args' must be a list if provided")
        if "kwargs" in mapping and not isinstance(mapping["kwargs"], dict):
            raise TypeError("'kwargs' must be a dict if provided")

    @staticmethod
    def _default_commands_path() -> str:
        return os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "config",
            "commands.json",
        )

    def _load_commands_index(self, path: str) -> Dict[str, List[str]]:
        try:
            with open(path, "r", encoding="utf-8") as file:
                data = json.load(file)
                # Normalize to List[str]
                index: Dict[str, List[str]] = {}
                for key, value in data.items():
                    if isinstance(value, list):
                        index[key] = [str(v) for v in value]
                    else:
                        index[key] = [str(value)]
                return index
        except Exception:
            self.logger.debug("Failed to load commands.json at %s", path, exc_info=True)
            return {}

    @staticmethod
    def _import_database():
        try:
            return __import__("backend.services.database", fromlist=["*"])
        except ImportError:
            try:
                return __import__("services.database", fromlist=["*"])
            except ImportError:
                try:
                    return __import__("database", fromlist=["*"])
                except ImportError:
                    return None


