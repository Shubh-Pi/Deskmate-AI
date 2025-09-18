import os
import platform
import subprocess
from datetime import datetime
from typing import Dict


def _get_logger():
    try:
        # Preferred: project logger service
        from backend.services import logger as project_logger  # type: ignore

        if hasattr(project_logger, "get_logger"):
            return project_logger.get_logger("automation.system")
    except Exception:
        pass

    # Fallback to std logging
    import logging

    lg = logging.getLogger("DeskmateAI.automation.system")
    if not lg.handlers:
        lg.propagate = True
    return lg


LOGGER = _get_logger()


def _ok(message: str) -> Dict[str, str]:
    return {"status": "success", "message": message}


def _err(message: str) -> Dict[str, str]:
    return {"status": "error", "message": message}


def _run(cmd: str) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)


def increase_volume() -> Dict[str, str]:
    try:
        import pyautogui  # type: ignore

        pyautogui.press("volumeup")
        LOGGER.info("Volume increased")
        return _ok("Volume increased")
    except Exception as error:
        LOGGER.exception("Failed to increase volume")
        return _err(str(error))


def decrease_volume() -> Dict[str, str]:
    try:
        import pyautogui  # type: ignore

        pyautogui.press("volumedown")
        LOGGER.info("Volume decreased")
        return _ok("Volume decreased")
    except Exception as error:
        LOGGER.exception("Failed to decrease volume")
        return _err(str(error))


def mute_volume() -> Dict[str, str]:
    try:
        import pyautogui  # type: ignore

        pyautogui.press("volumemute")
        LOGGER.info("Volume muted")
        return _ok("Volume muted")
    except Exception as error:
        LOGGER.exception("Failed to mute volume")
        return _err(str(error))


def take_screenshot() -> Dict[str, str]:
    try:
        import pyautogui  # type: ignore

        screenshots_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "screenshots",
        )
        os.makedirs(screenshots_dir, exist_ok=True)
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
        path = os.path.join(screenshots_dir, f"screenshot_{ts}.png")
        image = pyautogui.screenshot()
        image.save(path)
        LOGGER.info("Screenshot saved: %s", path)
        return _ok(f"Screenshot saved: {path}")
    except Exception as error:
        LOGGER.exception("Failed to take screenshot")
        return _err(str(error))


def adjust_brightness(level: int) -> Dict[str, str]:
    try:
        level = max(0, min(100, int(level)))
        system = platform.system().lower()
        if system == "windows":
            # Use PowerShell WMI call; may require privileges and supported hardware
            cmd = (
                f"powershell -NoProfile -Command "
                f"\"$b=(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods);"
                f"if($b){{$b.WmiSetBrightness(1,{level})}}\""
            )
            result = _run(cmd)
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "Brightness command failed")
        else:
            # Not implemented for other OS in this scaffold
            raise NotImplementedError("Brightness control not supported on this OS in scaffold")
        LOGGER.info("Brightness set to %s", level)
        return _ok(f"Brightness set to {level}")
    except Exception as error:
        LOGGER.exception("Failed to adjust brightness")
        return _err(str(error))


def control_wifi(enable: bool) -> Dict[str, str]:
    try:
        system = platform.system().lower()
        if system == "windows":
            state = "enabled" if enable else "disabled"
            # Interface name may vary; 'Wi-Fi' is default on many systems
            cmd = f'netsh interface set interface name="Wi-Fi" admin={state}'
            result = _run(cmd)
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "netsh failed")
        else:
            raise NotImplementedError("Wi-Fi control not supported on this OS in scaffold")
        LOGGER.info("Wi-Fi %s", "enabled" if enable else "disabled")
        return _ok(f"Wi-Fi {'enabled' if enable else 'disabled'}")
    except Exception as error:
        LOGGER.exception("Failed to control Wi-Fi")
        return _err(str(error))


def shutdown() -> Dict[str, str]:
    try:
        system = platform.system().lower()
        if system == "windows":
            _run("shutdown /s /t 0")
        else:
            raise NotImplementedError("Shutdown not supported on this OS in scaffold")
        LOGGER.warning("System shutdown initiated")
        return _ok("Shutdown initiated")
    except Exception as error:
        LOGGER.exception("Failed to shutdown")
        return _err(str(error))


def restart() -> Dict[str, str]:
    try:
        system = platform.system().lower()
        if system == "windows":
            _run("shutdown /r /t 0")
        else:
            raise NotImplementedError("Restart not supported on this OS in scaffold")
        LOGGER.warning("System restart initiated")
        return _ok("Restart initiated")
    except Exception as error:
        LOGGER.exception("Failed to restart")
        return _err(str(error))


def lock_screen() -> Dict[str, str]:
    try:
        system = platform.system().lower()
        if system == "windows":
            _run("rundll32.exe user32.dll,LockWorkStation")
        else:
            raise NotImplementedError("Lock screen not supported on this OS in scaffold")
        LOGGER.info("Screen locked")
        return _ok("Screen locked")
    except Exception as error:
        LOGGER.exception("Failed to lock screen")
        return _err(str(error))


