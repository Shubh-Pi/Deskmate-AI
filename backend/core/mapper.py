import json
import logging
import os
from typing import Any, Callable, Dict, List, Optional, Tuple


def _get_logger() -> logging.Logger:
    logger = logging.getLogger("DeskmateAI.AdaptiveMapper")
    if not logger.handlers:
        logger.propagate = True
    return logger


class AdaptiveMapper:
    """Map natural language commands to concrete automation functions.

    Data sources:
    - Config synonyms from config/commands.json (action_key -> [synonyms])
    - Persistent mappings from services.database (command_text -> mapping)

    Resolution strategy:
    1) Exact mapping lookup in database
    2) Fuzzy match against known database commands and config action keys/synonyms
    3) If matched action key maps via registry, return that mapping
    4) Otherwise delegate to Learner to confirm or manually map, then read mapping from database

    NLP extension:
    An optional intent_recognizer may be injected. It should implement:
        recognize_intent(text: str) -> Tuple[str, float] where str is an action key and float is confidence [0,1].
    If provided and high confidence, we prefer the recognizer result over fuzzy matching.
    """

    def __init__(
        self,
        intent_recognizer: Optional[Callable[[str], Tuple[str, float]]] = None,
        confirm_callback: Optional[Callable[[str], bool]] = None,
        manual_map_callback: Optional[Callable[[str, List[str]], Dict[str, Any]]] = None,
        commands_config_path: Optional[str] = None,
    ) -> None:
        self.logger = _get_logger()
        self.intent_recognizer = intent_recognizer
        self.confirm_callback = confirm_callback or self._default_confirm
        self.manual_map_callback = manual_map_callback or self._default_manual_map
        self.commands_config_path = commands_config_path or self._default_commands_path()

        # Initialize registry and learner directly; keep database helper
        try:
            from backend.core.registry import CommandRegistry  # type: ignore

            self._registry = CommandRegistry()
        except Exception:
            self._registry = None
        self._db = self._import_database()
        try:
            from backend.core.learner import Learner  # type: ignore

            self._learner_ctor = Learner
        except Exception:
            self._learner_ctor = None

        self._commands_index = self._load_commands_index(self.commands_config_path)

    def resolve_command(self, text_command: str) -> Dict[str, Any]:
        mapping = self._get_db_mapping(text_command)
        if mapping:
            enriched = self._enrich_mapping_with_args(text_command, mapping)
            return enriched

        action_key, score = self._recognize_or_match(text_command)
        if action_key and score >= 0.8:
            mapping = self._map_action_via_registry(action_key)
            if mapping:
                enriched = self._enrich_mapping_with_args(text_command, mapping)
                return enriched

        db_like_mapping = self._match_existing_db_command(text_command)
        if db_like_mapping:
            return db_like_mapping

        if action_key:
            try:
                if self.confirm_callback(action_key):
                    mapping = self._map_action_via_registry(action_key)
                    if mapping:
                        enriched = self._enrich_mapping_with_args(text_command, mapping)
                        return enriched
            except Exception:
                self.logger.debug("Confirmation callback failed", exc_info=True)

        if not self._learner_ctor:
            raise RuntimeError("Learner is not available to handle unknown commands")

        try:
            learner_instance = self._learner_ctor(
            confirm_callback=self.confirm_callback,
            manual_map_callback=self.manual_map_callback,
            commands_config_path=self.commands_config_path,
        )
        except Exception as error:
            self.logger.debug("Failed to instantiate Learner: %s", error, exc_info=True)
            raise RuntimeError("Adaptive learner unavailable") from error

        learn_result = learner_instance.handle_unknown(text_command)
        if learn_result.get("status") != "success":
            raise RuntimeError("Failed to learn mapping for unknown command")

        mapping = self._get_db_mapping(text_command)
        if not mapping:
            raise RuntimeError("Mapping not found in database after learning step")
        enriched = self._enrich_mapping_with_args(text_command, mapping)
        return enriched

    # Matching helpers

    def _recognize_or_match(self, text_command: str) -> Tuple[Optional[str], float]:
        from fuzzywuzzy import fuzz

        if self.intent_recognizer:
            try:
                intent_key, confidence = self.intent_recognizer(text_command)
                if intent_key:
                    return intent_key, float(confidence)
            except Exception:
                self.logger.debug("Intent recognizer failed", exc_info=True)

        best_key: Optional[str] = None
        best_score = 0
        for action_key, synonyms in self._commands_index.items():
            candidates = [action_key] + list(synonyms)
            score = max(fuzz.token_set_ratio(text_command, c) for c in candidates)
            if score > best_score:
                best_key, best_score = action_key, score

        normalized = best_score / 100.0
        return (best_key, normalized) if best_key else (None, 0.0)

    def _match_existing_db_command(self, text_command: str) -> Optional[Dict[str, Any]]:
        try:
            commands = self._list_db_commands()
        except Exception:
            commands = []
        if not commands:
            return None

        from fuzzywuzzy import fuzz

        best_text: Optional[str] = None
        best_score = 0
        for cmd_text in commands:
            score = fuzz.token_set_ratio(text_command, cmd_text)
            if score > best_score:
                best_text, best_score = cmd_text, score

        if best_text and best_score >= 80:
            return self._get_db_mapping(best_text)
        return None

    # Data access helpers

    def _get_db_mapping(self, command_text: str) -> Optional[Dict[str, Any]]:
        if not self._db:
            return None

        if hasattr(self._db, "Database"):
            db = self._db.Database()
            if hasattr(db, "get_mapping"):
                return db.get_mapping(command_text)

        if hasattr(self._db, "get_mapping"):
            return self._db.get_mapping(command_text)
        return None

    def _list_db_commands(self) -> List[str]:
        if not self._db:
            return []

        if hasattr(self._db, "Database"):
            db = self._db.Database()
            if hasattr(db, "list_commands"):
                return list(db.list_commands())

        if hasattr(self._db, "list_commands"):
            return list(self._db.list_commands())
        return []

    def _map_action_via_registry(self, action_key: str) -> Optional[Dict[str, Any]]:
        if not self._registry:
            return None
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

        # Support either the CommandRegistry schema {module_path,function_name}
        # or a direct mapping {module,function}
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

        return {"module": module, "function": function, "args": [], "kwargs": {}}

    # Argument enrichment helpers

    def _enrich_mapping_with_args(self, text_command: str, mapping: Dict[str, Any]) -> Dict[str, Any]:
        try:
            module = (mapping.get("module") or "").strip()
            function = (mapping.get("function") or "").strip()
            args = list(mapping.get("args", []) or [])
            kwargs = dict(mapping.get("kwargs", {}) or {})

            if args:  # respect existing args
                return {"module": module, "function": function, "args": args, "kwargs": kwargs}

            text = (text_command or "").strip()
            lower = text.lower()

            if module == "apps" and function in {"open_app", "close_app"}:
                # Extract app name after first keyword like 'open' or 'close'
                parts = lower.split()
                if len(parts) >= 2:
                    target = text.split(" ", 1)[1].strip()
                    if target:
                        args = [target]

            elif module == "browser" and function == "open_url":
                # Try to extract URL or fallback to building a domain
                import re
                m = re.search(r"(https?://\S+|www\.\S+|\w+\.\w{2,})", text, re.IGNORECASE)
                if m:
                    args = [m.group(1)]
                else:
                    # Heuristic: 'open something' -> https://something.com
                    if lower.startswith("open ") and len(lower.split()) >= 2:
                        token = lower.split()[1]
                        args = [f"https://{token}.com"]

            elif module == "browser" and function == "search_google":
                # Use remainder after 'search' or whole text
                q = text
                if lower.startswith("search "):
                    q = text.split(" ", 1)[1].strip() or text
                args = [q]

            elif module == "youtube" and function in {"play_video", "search_and_play"}:
                # Use remainder after 'play' or 'search'
                if " " in text:
                    q = text.split(" ", 1)[1].strip()
                else:
                    q = text
                args = [q]

            # Return enriched mapping
            return {"module": module, "function": function, "args": args, "kwargs": kwargs}
        except Exception:
            # On any failure, return original mapping
            return mapping

    # Utilities

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
    def _import_registry():
        # Kept for backward compatibility; not used after direct init
        try:
            from backend.core.registry import CommandRegistry  # type: ignore

            return CommandRegistry()
        except Exception:
                    return None

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

    @staticmethod
    def _import_learner():
        # Kept for backward compatibility; not used after direct init
        try:
            from backend.core.learner import Learner  # type: ignore

            return Learner
        except Exception:
                    return None

    # Default interactive callbacks (can be replaced in UI layer)

    @staticmethod
    def _default_confirm(suggested_action: str) -> bool:
        try:
            answer = input(f"Did you mean '{suggested_action}'? [y/N]: ").strip().lower()
            return answer in {"y", "yes"}
        except Exception:
            return False

    @staticmethod
    def _default_manual_map(text_command: str, available_actions: List[str]) -> Dict[str, Any]:
        print("Unknown command. Please map it to an existing action.")
        if available_actions:
            print("Available actions:")
            for action in available_actions:
                print(f" - {action}")
        module = input("Enter module name (e.g., 'browser'): ").strip()
        function = input("Enter function name (e.g., 'open'): ").strip()
        return {"module": module, "function": function, "args": [], "kwargs": {}}


# Module-level convenience functions expected by CommandHandler
def resolve_command(text_command: str) -> Dict[str, Any]:
    mapper = AdaptiveMapper()
    return mapper.resolve_command(text_command)


def map(text_command: str) -> Dict[str, Any]:
    return resolve_command(text_command)


