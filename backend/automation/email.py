import os
import ssl
import smtplib
import imaplib
import email
from email.mime.text import MIMEText
from typing import Dict, List

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    yaml = None  # type: ignore


def _get_logger():
    try:
        from backend.services import logger as project_logger  # type: ignore

        if hasattr(project_logger, "get_logger"):
            return project_logger.get_logger("automation.email")
    except Exception:
        pass

    import logging

    lg = logging.getLogger("DeskmateAI.automation.email")
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


def _settings_path() -> str:
    # DeskmateAI/config/settings.yaml
    base = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    return os.path.join(base, "config", "settings.yaml")


def _load_settings() -> Dict[str, object]:
    path = _settings_path()
    if not os.path.exists(path):
        return {}
    try:
        if yaml is None:
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        LOGGER.debug("Failed to load settings.yaml", exc_info=True)
        return {}


def _email_config() -> Dict[str, object]:
    cfg = _load_settings()
    # Expected structure under settings: { email: { smtp: {...}, imap: {...} } }
    email_cfg = (cfg.get("email") or {}) if isinstance(cfg, dict) else {}
    smtp_cfg = (email_cfg.get("smtp") or {}) if isinstance(email_cfg, dict) else {}
    imap_cfg = (email_cfg.get("imap") or {}) if isinstance(email_cfg, dict) else {}

    # Allow environment overrides
    smtp_cfg.setdefault("host", os.getenv("SMTP_HOST"))
    smtp_cfg.setdefault("port", int(os.getenv("SMTP_PORT", "587")))
    smtp_cfg.setdefault("username", os.getenv("SMTP_USERNAME"))
    smtp_cfg.setdefault("password", os.getenv("SMTP_PASSWORD"))
    smtp_cfg.setdefault("use_tls", True)
    smtp_cfg.setdefault("from", os.getenv("SMTP_FROM"))

    imap_cfg.setdefault("host", os.getenv("IMAP_HOST"))
    imap_cfg.setdefault("port", int(os.getenv("IMAP_PORT", "993")))
    imap_cfg.setdefault("username", os.getenv("IMAP_USERNAME"))
    imap_cfg.setdefault("password", os.getenv("IMAP_PASSWORD"))
    imap_cfg.setdefault("use_ssl", True)

    return {"smtp": smtp_cfg, "imap": imap_cfg}


def send_email(to: str, subject: str, body: str) -> Dict[str, object]:
    try:
        cfg = _email_config()["smtp"]
        host = cfg.get("host")
        port = int(cfg.get("port") or 587)
        username = cfg.get("username")
        password = cfg.get("password")
        use_tls = bool(cfg.get("use_tls", True))
        sender = cfg.get("from") or username

        if not all([host, port, username, password, sender, to]):
            return _err("SMTP configuration or parameters missing")

        msg = MIMEText(body or "", _charset="utf-8")
        msg["Subject"] = subject or "(no subject)"
        msg["From"] = sender
        msg["To"] = to

        LOGGER.info("Sending email to %s via %s:%s", to, host, port)
        context = ssl.create_default_context()
        with smtplib.SMTP(host, port, timeout=20) as server:
            server.ehlo()
            if use_tls:
                server.starttls(context=context)
                server.ehlo()
            server.login(username, password)
            server.sendmail(sender, [to], msg.as_string())
        return _ok("Email sent", to=to, subject=subject)
    except Exception as error:
        LOGGER.exception("Failed to send email to %s", to)
        return _err(str(error))


def draft_email(to: str, subject: str, body: str) -> Dict[str, object]:
    try:
        base = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        drafts_dir = os.path.join(base, "data", "drafts")
        os.makedirs(drafts_dir, exist_ok=True)
        file_name = subject.strip().replace(" ", "_")[:50] if subject else "draft"
        path = os.path.join(drafts_dir, f"{file_name}.eml")

        msg = MIMEText(body or "", _charset="utf-8")
        msg["Subject"] = subject or "(no subject)"
        msg["To"] = to or ""

        with open(path, "w", encoding="utf-8") as f:
            f.write(msg.as_string())
        LOGGER.info("Draft saved: %s", path)
        return _ok("Draft saved", path=path)
    except Exception as error:
        LOGGER.exception("Failed to save draft")
        return _err(str(error))


def read_unread_emails() -> Dict[str, object]:
    try:
        cfg = _email_config()["imap"]
        host = cfg.get("host")
        port = int(cfg.get("port") or 993)
        username = cfg.get("username")
        password = cfg.get("password")
        use_ssl = bool(cfg.get("use_ssl", True))

        if not all([host, port, username, password]):
            return _err("IMAP configuration missing")

        LOGGER.info("Reading unread emails from %s", host)
        if use_ssl:
            imap = imaplib.IMAP4_SSL(host, port)
        else:
            imap = imaplib.IMAP4(host, port)
        try:
            imap.login(username, password)
            imap.select("INBOX")
            status, data = imap.search(None, "UNSEEN")
            if status != "OK":
                return _err("IMAP search failed")
            ids = data[0].split()
            emails: List[Dict[str, str]] = []
            for eid in ids[:20]:  # cap to 20 for demo
                status, msg_data = imap.fetch(eid, "(RFC822)")
                if status != "OK":
                    continue
                msg = email.message_from_bytes(msg_data[0][1])
                subject = msg.get("Subject", "")
                from_addr = msg.get("From", "")
                emails.append({"from": from_addr, "subject": subject})
            return _ok("Fetched unread emails", emails=emails)
        finally:
            try:
                imap.logout()
            except Exception:
                pass
    except Exception as error:
        LOGGER.exception("Failed to read unread emails")
        return _err(str(error))


