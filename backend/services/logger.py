import os
from pathlib import Path
from typing import Optional

try:
    from loguru import logger as _logger  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    _logger = None  # type: ignore


_CONFIGURED = False


def _logs_dir() -> Path:
    base = Path(__file__).resolve().parents[2]  # .../DeskmateAI
    logs = base / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    return logs


def _configure_logger() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    if _logger is None:
        _CONFIGURED = True
        return

    # Remove default sink to avoid duplicate console logs when reloading
    _logger.remove()

    # Define custom security level before adding sinks
    try:
        _logger.level("SECURITY_EVENT")
    except Exception:
        # Create if not exists; place between WARNING (30) and ERROR (40)
        _logger.level("SECURITY_EVENT", no=35, color="<red>")

    # Console sink
    _logger.add(
        sink=lambda msg: print(msg, end=""),
        colorize=True,
        backtrace=False,
        diagnose=False,
        level="INFO",
        enqueue=True,
    )

    # File sink
    log_file = _logs_dir() / "assistant.log"
    _logger.add(
        str(log_file),
        rotation="10 MB",
        retention="14 days",
        encoding="utf-8",
        level="DEBUG",
        enqueue=True,
    )

    _CONFIGURED = True


def get_logger(name: Optional[str] = None):
    """Return a configured Loguru logger, optionally with a bound name."""
    _configure_logger()
    if _logger is None:
        import logging

        lg = logging.getLogger(name or "DeskmateAI")
        if not lg.handlers:
            lg.propagate = True
        return lg
    return _logger.bind(name=name) if name else _logger


# Convenience passthrough API for easy imports: from backend.services.logger import info, warning, error, success

def info(message: str, *args, **kwargs) -> None:
    get_logger().info(message, *args, **kwargs)


def warning(message: str, *args, **kwargs) -> None:
    get_logger().warning(message, *args, **kwargs)


def error(message: str, *args, **kwargs) -> None:
    get_logger().error(message, *args, **kwargs)


def success(message: str, *args, **kwargs) -> None:
    # Loguru includes a SUCCESS level by default
    get_logger().success(message, *args, **kwargs)


def security_event(message: str, *args, **kwargs) -> None:
    get_logger().log("SECURITY_EVENT", message, *args, **kwargs)


