import time
import urllib.parse
import webbrowser
from typing import Dict, List


def _get_logger():
    try:
        from backend.services import logger as project_logger  # type: ignore

        if hasattr(project_logger, "get_logger"):
            return project_logger.get_logger("automation.whatsapp")
    except Exception:
        pass

    import logging

    lg = logging.getLogger("DeskmateAI.automation.whatsapp")
    if not lg.handlers:
        lg.propagate = True
    return lg


LOGGER = _get_logger()


def _ok(message: str) -> Dict[str, str]:
    return {"status": "success", "message": message}


def _err(message: str) -> Dict[str, str]:
    return {"status": "error", "message": message}


def _type_text(text: str) -> None:
    try:
        import keyboard  # type: ignore

        keyboard.write(text)
        return
    except Exception:
        pass

    try:
        import pyautogui  # type: ignore

        pyautogui.typewrite(text, interval=0.02)
    except Exception:
        return


def _press(keys: str) -> None:
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
        return


def open_chat(contact: str) -> Dict[str, str]:
    try:
        if not contact:
            return _err("Contact is required")
        q = urllib.parse.quote(contact)
        url = f"https://web.whatsapp.com/send?phone=&text=&type=phone&app_absent=0"
        webbrowser.open("https://web.whatsapp.com/", new=2)
        LOGGER.info("Opened WhatsApp Web home")
        time.sleep(3.0)

        # Focus search bar: WhatsApp Web usually puts focus in the chat list; try Ctrl+K then type name
        _press("ctrl+k")
        time.sleep(0.2)
        _type_text(contact)
        time.sleep(0.4)
        _press("enter")
        LOGGER.info("Attempted to open chat: %s", contact)
        return _ok(f"Opened chat with {contact} (best-effort)")
    except Exception as error:
        LOGGER.exception("Failed to open WhatsApp chat for: %s", contact)
        return _err(str(error))


def send_message(contact: str, message: str) -> Dict[str, str]:
    try:
        if not contact or not message:
            return _err("Contact and message are required")
        # Ensure WhatsApp Web is open
        webbrowser.open("https://web.whatsapp.com/", new=2)
        time.sleep(3.0)

        # Open chat and type message
        _press("ctrl+k")
        time.sleep(0.2)
        _type_text(contact)
        time.sleep(0.4)
        _press("enter")
        time.sleep(0.6)
        _type_text(message)
        time.sleep(0.2)
        _press("enter")
        LOGGER.info("Simulated sending message to %s: %s", contact, message)
        return _ok("Message sent (simulated)")
    except Exception as error:
        LOGGER.exception("Failed to send WhatsApp message to: %s", contact)
        return _err(str(error))


def read_notifications() -> Dict[str, str]:
    try:
        # Demo: no real scraping; just ensure WhatsApp Web is open
        webbrowser.open("https://web.whatsapp.com/", new=2)
        LOGGER.info("Opened WhatsApp Web for notifications (demo)")
        return _ok("Notifications read (demo)")
    except Exception as error:
        LOGGER.exception("Failed to read WhatsApp notifications")
        return _err(str(error))


