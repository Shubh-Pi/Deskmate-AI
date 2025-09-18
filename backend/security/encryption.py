import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from dotenv import load_dotenv
from backend.services import logger as project_logger


_FERNET_ENV_KEY = "FERNET_KEY"


def _load_key_from_env() -> Optional[bytes]:
    # Load .env if present
    try:
        load_dotenv(override=False)
    except Exception:
        pass

    key = os.getenv(_FERNET_ENV_KEY)
    if not key:
        return None
    try:
        # Expect URL-safe base64-encoded 32-byte key
        return key.encode("utf-8")
    except Exception:
        return None


def _get_fernet() -> Fernet:
    key = _load_key_from_env()
    if not key:
        # Log and raise for visibility
        try:
            project_logger.error("FERNET_KEY not set; encryption unavailable")
        except Exception:
            pass
        raise RuntimeError(
            "Missing FERNET_KEY in environment/.env. Generate with: "
            "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    return Fernet(key)


def encrypt_data(data: str) -> str:
    """Encrypt a UTF-8 string and return a token string."""
    if data is None:
        data = ""
    try:
        f = _get_fernet()
        token = f.encrypt(data.encode("utf-8"))
        return token.decode("utf-8")
    except Exception as error:
        try:
            project_logger.error("Encryption error: {}", str(error))
        except Exception:
            pass
        raise


def decrypt_data(token: str) -> str:
    """Decrypt a token string and return the original UTF-8 string."""
    if not token:
        return ""
    try:
        f = _get_fernet()
        data = f.decrypt(token.encode("utf-8"))
        return data.decode("utf-8")
    except InvalidToken as error:
        try:
            project_logger.error("Decryption failed: invalid token or key")
        except Exception:
            pass
        raise ValueError("Invalid encryption token or key") from error
    except Exception as error:
        try:
            project_logger.error("Decryption error: {}", str(error))
        except Exception:
            pass
        raise


def rotate_key(update_env: bool = True) -> str:
    """Generate a new Fernet key and optionally persist it into .env.

    Returns the new key as a UTF-8 string and logs a key rotation event.
    """
    new_key = Fernet.generate_key().decode("utf-8")
    try:
        project_logger.security_event("Encryption key rotation initiated")
    except Exception:
        pass

    if update_env:
        # Try to update a .env file at project root
        try:
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            env_path = os.path.join(project_root, ".env")
            # Load existing contents
            contents = ""
            if os.path.exists(env_path):
                with open(env_path, "r", encoding="utf-8") as f:
                    contents = f.read()
            lines = [] if not contents else contents.splitlines()
            updated = False
            for i, line in enumerate(lines):
                if line.startswith(f"{_FERNET_ENV_KEY}="):
                    lines[i] = f"{_FERNET_ENV_KEY}={new_key}"
                    updated = True
                    break
            if not updated:
                lines.append(f"{_FERNET_ENV_KEY}={new_key}")
            with open(env_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            os.environ[_FERNET_ENV_KEY] = new_key
            try:
                project_logger.security_event("Encryption key rotated and .env updated")
            except Exception:
                pass
        except Exception as error:
            try:
                project_logger.error("Key rotation write failure: {}", str(error))
            except Exception:
                pass
            # Still return key; caller may handle persistence
    return new_key


