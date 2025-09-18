import time
import urllib.parse
import webbrowser
from typing import Dict


def _get_logger():
    try:
        from backend.services import logger as project_logger  # type: ignore

        if hasattr(project_logger, "get_logger"):
            return project_logger.get_logger("automation.youtube")
    except Exception:
        pass

    import logging

    lg = logging.getLogger("DeskmateAI.automation.youtube")
    if not lg.handlers:
        lg.propagate = True
    return lg


LOGGER = _get_logger()


def _ok(message: str) -> Dict[str, str]:
    return {"status": "success", "message": message}


def _err(message: str) -> Dict[str, str]:
    return {"status": "error", "message": message}


def _press(keys: str) -> None:
    """Try keyboard first, then pyautogui as fallback."""
    try:
        import keyboard  # type: ignore

        keyboard.press_and_release(keys)
        return
    except Exception:
        pass

    try:
        import pyautogui  # type: ignore

        if "+" in keys:
            parts = keys.split("+")
            pyautogui.hotkey(*parts)
        else:
            pyautogui.press(keys)
    except Exception:
        # If no input libraries available, ignore
        return


def play_video(query: str) -> Dict[str, str]:
    """Open YouTube search for query and attempt to play the first result."""
    try:
        if not query:
            return _err("Query is required")
        q = urllib.parse.quote_plus(query)
        url = f"https://www.youtube.com/results?search_query={q}"
        webbrowser.open(url, new=2)
        LOGGER.info("Opened YouTube search for: %s", query)
        time.sleep(2.5)
        # Attempt to focus results and open first video (best-effort)
        # YouTube usually focuses search box; try Tab+Enter a few times
        for _ in range(3):
            _press("tab")
            time.sleep(0.1)
        _press("enter")
        time.sleep(2.0)
        # Ensure playing
        _press("k")  # toggle play/pause
        return _ok("YouTube video playback started (best-effort)")
    except Exception as error:
        LOGGER.exception("Failed to play YouTube video for: %s", query)
        return _err(str(error))


def pause_video() -> Dict[str, str]:
    try:
        _press("k")  # toggle play/pause
        LOGGER.info("YouTube video paused (toggle)")
        return _ok("YouTube video paused (toggle)")
    except Exception as error:
        LOGGER.exception("Failed to pause YouTube video")
        return _err(str(error))


def skip_video() -> Dict[str, str]:
    try:
        _press("shift+n")  # next video in playlist
        LOGGER.info("Skipped to next YouTube video")
        return _ok("Skipped to next video")
    except Exception as error:
        LOGGER.exception("Failed to skip YouTube video")
        return _err(str(error))


def mute_video() -> Dict[str, str]:
    try:
        _press("m")
        LOGGER.info("YouTube video muted (toggle)")
        return _ok("YouTube video muted (toggle)")
    except Exception as error:
        LOGGER.exception("Failed to mute YouTube video")
        return _err(str(error))


def search_and_play(query: str) -> Dict[str, str]:
    """Alias to play_video for clarity."""
    return play_video(query)


