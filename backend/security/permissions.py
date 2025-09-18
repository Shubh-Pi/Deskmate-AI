import json
import os
from typing import Dict, Optional

from backend.services import logger as project_logger


def _get_logger():
    try:
        return project_logger.get_logger("security.permissions")
    except Exception:
        import logging

        lg = logging.getLogger("DeskmateAI.security.permissions")
        if not lg.handlers:
            lg.propagate = True
        return lg


LOGGER = _get_logger()


def _project_base() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


def _users_db_path() -> str:
    return os.path.join(_project_base(), "data", "users.json")


def _read_json(path: str) -> Dict[str, dict]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


# Categories map to top-level automation modules
# E.g., "system.adjust_brightness" -> category "system"
SAFE_READ_ONLY_FUNCTIONS = {
    "browser.open_url",
    "browser.search_google",
    "browser.get_wikipedia_summary",
    "youtube.play_video",
    "youtube.search_and_play",
    "apps.list_running_apps",
}

ROLE_POLICIES = {
    "admin": {
        "allow_all": True,
        "blocked_functions": set(),
        "allowed_categories": set(),
    },
    "standard_user": {
        "allow_all": False,
        "allowed_categories": {"browser", "youtube", "apps", "email", "whatsapp"},
        "blocked_functions": {
            "system.shutdown",
            "system.restart",
        },
    },
    "guest": {
        "allow_all": False,
        "allowed_categories": set(),  # only explicit read-only functions
        "blocked_functions": set(),
    },
}


def _get_user_role(user_id: str) -> str:
    users = _read_json(_users_db_path())
    role = "guest"
    if user_id in users and isinstance(users[user_id], dict):
        r = users[user_id].get("role")
        if isinstance(r, str) and r:
            role = r
    return role if role in ROLE_POLICIES else "guest"


def _function_path_from_command(command: str) -> str:
    # Accept forms like "module:function" or "module.function" or full dotted path
    if ":" in command:
        module, func = command.split(":", 1)
        return f"{module}.{func}"
    return command


def _category_from_function(function_path: str) -> Optional[str]:
    # Expected like "backend.automation.system.adjust_brightness" or "system.adjust_brightness"
    parts = function_path.split(".")
    if not parts:
        return None
    # Find segment matching automation module name
    if "automation" in parts:
        idx = parts.index("automation")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    # fallback to first segment as category
    return parts[0]


def check_permission(user_id: str, command: str) -> bool:
    role = _get_user_role(user_id)
    policy = ROLE_POLICIES.get(role, ROLE_POLICIES["guest"])

    function_path = _function_path_from_command(command)
    simple_fn = ".".join(function_path.split(".")[-2:]) if "." in function_path else function_path

    if policy.get("allow_all"):
        LOGGER.debug("Access granted (admin): user=%s command=%s", user_id, command)
        return True

    if role == "guest":
        allowed = simple_fn in SAFE_READ_ONLY_FUNCTIONS
        if allowed:
            LOGGER.debug("Access granted (guest): user=%s command=%s", user_id, command)
        else:
            project_logger.security_event("Access denied: user=%s role=guest command=%s", user_id, command)
        return allowed

    # Standard user: category must be allowed and function not blocked
    category = _category_from_function(function_path) or ""
    if simple_fn in policy.get("blocked_functions", set()):
        project_logger.security_event("Access denied (blocked function): user=%s command=%s", user_id, command)
        return False
    if category in policy.get("allowed_categories", set()):
        LOGGER.debug("Access granted: user=%s role=%s command=%s", user_id, role, command)
        return True
    project_logger.security_event("Access denied (category): user=%s role=%s command=%s category=%s", user_id, role, command, category)
    return False


def enforce_permission(user_id: str, command: str) -> None:
    if not check_permission(user_id, command):
        LOGGER.warning("Permission denied: user=%s command=%s", user_id, command)
        raise PermissionError("Unauthorized command for this role")


