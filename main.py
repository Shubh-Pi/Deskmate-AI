import json
import os
import sys
import getpass
import logging
import logging.config
from typing import Any, Dict

try:
    import yaml  # type: ignore
except Exception:
    yaml = None  # type: ignore

# Backend services and core
from backend.services import logger as project_logger
from backend.services import database as db
from backend.services import undo_redo
from backend.core.command_handler import CommandHandler
from backend.core.registry import CommandRegistry
from backend.core import learner as core_learner

# Automation modules (import to ensure discovery/availability)
from backend.automation import system, apps, browser, youtube, whatsapp, email  # noqa: F401

# Security
from backend.security import auth
from backend.services.database import set_user_role

set_user_role("default_user", "admin")


def project_root() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def config_path(*parts: str) -> str:
    return os.path.join(project_root(), "config", *parts)


def data_path(*parts: str) -> str:
    return os.path.join(project_root(), "data", *parts)


def load_settings() -> Dict[str, Any]:
    path = config_path("settings.yaml")
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        if yaml is None:
            return {}
        return yaml.safe_load(f) or {}


def load_commands_index() -> Dict[str, Any]:
    path = config_path("commands.json")
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f) or {}


def setup_logging() -> None:
    conf = config_path("logging.conf")
    try:
        if os.path.exists(conf):
            logging.config.fileConfig(conf, disable_existing_loggers=False)
        else:
            # Fallback to project logger service minimal config
            project_logger.get_logger().info("logging.conf not found; using default logger config")
    except Exception as error:
        print(f"Failed to setup logging: {error}", file=sys.stderr)


def initialize_services() -> Dict[str, Any]:
    services: Dict[str, Any] = {}

    # Database (tables created lazily on manager init)
    services["db"] = db.DatabaseManager()

    # Undo/Redo manager is module-level in services.undo_redo
    services["undo_redo"] = undo_redo

    # Command registry: discover automation functions
    services["registry"] = CommandRegistry()

    return services


def authenticate_user_interactive() -> Dict[str, Any]:
    print("Welcome to Deskmate AI")
    user_id = os.getenv("DESKMATE_USER", "default_user")
    try:
        password = getpass.getpass("Enter password: ")
    except Exception:
        password = input("Enter password: ")
    result = auth.authenticate_user(user_id=user_id, password=password)
    if result.get("status") == "success":
        project_logger.success("User {} authenticated", user_id)
        return {"user_id": user_id, "tokens": {"access": result.get("access_token"), "refresh": result.get("refresh_token")}}
    project_logger.security_event("Authentication failed for user {}", user_id)
    print("Authentication failed. Exiting.")
    sys.exit(1)


def main() -> None:
    # Step 1: Setup logging
    setup_logging()
    log = project_logger.get_logger("main")

    # Step 2: Load configuration and commands index
    settings = load_settings()
    commands_index = load_commands_index()
    log.info("Settings loaded; commands index entries: {}", len(commands_index))

    # Step 3: Initialize services
    services = initialize_services()
    registry = services["registry"]
    log.info("Discovered {} automation commands", len(registry.list_commands()))

    # Step 4: Authentication
    session = authenticate_user_interactive()
    user_id = session["user_id"]
    access_token = session["tokens"]["access"]
    log.info("Session established for {}", user_id)

    # Step 5: Main loop
    handler = CommandHandler(user_id=user_id)
    print("Type 'undo', 'redo', or 'exit' to control the session.")
    while True:
        try:
            text = input("DeskmateAI> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not text:
            continue

        if text.lower() == "exit":
            break
        if text.lower() == "undo":
            result = handler.undo()
            print(result.get("message"))
            continue
        if text.lower() == "redo":
            result = handler.redo()
            print(result.get("message"))
            continue

        # Clear a specific stored mapping
        if text.lower().startswith("clear mapping "):
            command_to_clear = text.replace("clear mapping ", "", 1).strip()
            try:
                core_learner.clear_command_mapping(command_to_clear)
            except Exception:
                log.debug("Failed to clear mapping for command: {}", command_to_clear)
            continue

        # Execute command via handler
        result = handler.execute(text)
        status = result.get("status")
        message = result.get("message")
        print(f"{status}: {message}")

        # Log to DB history if function executed is known
        func = result.get("function_executed")
        if func:
            try:
                db.log_history(command=text, action=func)
            except Exception:
                log.debug("Failed to write history for command: {}", text)

    # Step 6: Graceful shutdown
    try:
        log.info("Shutting down...")
        # If we had persistent handles, we would close them here.
    except Exception:
        pass
    print("Goodbye!")


if __name__ == "__main__":
    main()


