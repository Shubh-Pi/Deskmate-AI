import os
import platform
import subprocess
from typing import Dict, List
try:
    import psutil  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    psutil = None  # type: ignore


def _get_logger():
    try:
        from backend.services import logger as project_logger  # type: ignore

        if hasattr(project_logger, "get_logger"):
            return project_logger.get_logger("automation.apps")
    except Exception:
        pass

    import logging

    lg = logging.getLogger("DeskmateAI.automation.apps")
    if not lg.handlers:
        lg.propagate = True
    return lg


LOGGER = _get_logger()


def _ok(message: str, **extra) -> Dict[str, object]:
    resp = {"status": "success", "message": message}
    if extra:
        resp.update(extra)
    return resp


def _err(message: str, **extra) -> Dict[str, object]:
    resp = {"status": "error", "message": message}
    if extra:
        resp.update(extra)
    return resp


def _platform() -> str:
    return platform.system().lower()


def _resolve_app_command(app_name: str) -> List[str]:
    name = (app_name or "").strip().lower()
    system = _platform()

    # Common mappings; extend as needed
    windows_map = {
        "chrome": ["cmd", "/c", "start", "", "chrome"],
        "google chrome": ["cmd", "/c", "start", "", "chrome"],
        "edge": ["cmd", "/c", "start", "", "msedge"],
        "firefox": ["cmd", "/c", "start", "", "firefox"],
        "notepad": ["notepad"],
        "vscode": ["cmd", "/c", "start", "", "code"],
        "code": ["cmd", "/c", "start", "", "code"],
        "whatsapp": ["cmd", "/c", "start", "", "whatsapp"]
    }

    linux_map = {
        "chrome": ["google-chrome"],
        "google chrome": ["google-chrome"],
        "chromium": ["chromium"],
        "firefox": ["firefox"],
        "vscode": ["code"],
        "code": ["code"],
        "whatsapp": ["flatpak", "run", "com.github.eneshecan.WhatsAppForLinux"],
        "gedit": ["gedit"],
        "text editor": ["gedit"],
    }

    if system == "windows" and name in windows_map:
        return windows_map[name]
    if system == "linux" and name in linux_map:
        return linux_map[name]

    # Default: attempt to run the provided name/path directly
    return [app_name]


def open_app(app_name: str) -> Dict[str, object]:
    try:
        cmd = _resolve_app_command(app_name)
        LOGGER.info("Opening app: %s -> %s", app_name, cmd)
        if _platform() == "windows":
            # Use shell for Windows "start" handling
            subprocess.Popen(cmd, shell=False)
        else:
            subprocess.Popen(cmd)
        return _ok(f"Launched {app_name}")
    except Exception as error:
        LOGGER.exception("Failed to open app: %s", app_name)
        return _err(str(error))


def close_app(app_name: str) -> Dict[str, object]:
    try:
        if psutil is None:
            return _err("psutil not available")
        target = (app_name or "").strip().lower()
        if not target:
            return _err("App name required")

        closed = 0
        for proc in psutil.process_iter(["name", "exe", "cmdline"]):
            try:
                name = (proc.info.get("name") or "").lower()
                exe = (proc.info.get("exe") or "").lower()
                cmdline = " ".join(proc.info.get("cmdline") or []).lower()
                if target in name or target in exe or target in cmdline:
                    proc.terminate()
                    closed += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        gone, alive = psutil.wait_procs(psutil.process_iter(), timeout=0.1)
        LOGGER.info("Closed %s instances of %s", closed, app_name)
        if closed == 0:
            return _err(f"No running processes matched '{app_name}'")
        return _ok(f"Closed {closed} process(es) for {app_name}")
    except Exception as error:
        LOGGER.exception("Failed to close app: %s", app_name)
        return _err(str(error))


def list_running_apps() -> Dict[str, object]:
    try:
        if psutil is None:
            return _err("psutil not available")
        names: List[str] = []
        for proc in psutil.process_iter(["name"]):
            try:
                name = proc.info.get("name")
                if name:
                    names.append(name)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        unique_sorted = sorted(set(names))
        LOGGER.info("Running apps listed: %s entries", len(unique_sorted))
        return _ok("Listed running apps", processes=unique_sorted)
    except Exception as error:
        LOGGER.exception("Failed to list running apps")
        return _err(str(error))


