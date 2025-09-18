import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import bcrypt
import jwt

from backend.services import logger as project_logger


def _get_logger():
    try:
        return project_logger.get_logger("security.auth")
    except Exception:
        import logging

        lg = logging.getLogger("DeskmateAI.security.auth")
        if not lg.handlers:
            lg.propagate = True
        return lg


LOGGER = _get_logger()


# ---------- Configuration helpers ----------


def _project_base() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


def _data_dir() -> str:
    path = os.path.join(_project_base(), "data")
    os.makedirs(path, exist_ok=True)
    return path


def _jwt_secret() -> str:
    return os.getenv("JWT_SECRET", "change-me-secret")


def _jwt_access_ttl_minutes() -> int:
    return int(os.getenv("JWT_ACCESS_MINUTES", "30"))


def _jwt_refresh_ttl_days() -> int:
    return int(os.getenv("JWT_REFRESH_DAYS", "7"))


# ---------- Failure tracking for suspicious activity ----------

_FAIL_WINDOW_SECONDS = int(os.getenv("AUTH_FAIL_WINDOW_SECONDS", "600"))  # 10 minutes
_FAIL_THRESHOLD = int(os.getenv("AUTH_FAIL_THRESHOLD", "5"))
_fail_tracker: Dict[str, List[float]] = {}


def _record_failure(user_id: str) -> None:
    now = time.time()
    items = _fail_tracker.get(user_id, [])
    # keep only within window
    items = [t for t in items if now - t <= _FAIL_WINDOW_SECONDS]
    items.append(now)
    _fail_tracker[user_id] = items
    if len(items) >= _FAIL_THRESHOLD:
        LOGGER.warning("Suspicious activity: multiple failed auth attempts for %s (%s in %ss)", user_id, len(items), _FAIL_WINDOW_SECONDS)


def _reset_failures(user_id: str) -> None:
    if user_id in _fail_tracker:
        _fail_tracker.pop(user_id, None)


# ---------- Storage: users and voiceprints ----------


def _users_db_path() -> str:
    return os.path.join(_data_dir(), "users.json")


def _voice_db_path() -> str:
    return os.path.join(_data_dir(), "voiceprint_db.json")


def _read_json(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _write_json(path: str, data: Dict[str, Any]) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# ---------- Voice utils ----------


def _cosine_similarity(v1: List[float], v2: List[float]) -> float:
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    num = sum(a * b for a, b in zip(v1, v2))
    den1 = sum(a * a for a in v1) ** 0.5
    den2 = sum(b * b for b in v2) ** 0.5
    if den1 == 0 or den2 == 0:
        return 0.0
    return float(num / (den1 * den2))


def _get_stored_voice_embedding(user_id: str) -> Optional[List[float]]:
    db = _read_json(_voice_db_path())
    embedding = db.get(user_id)
    if isinstance(embedding, list) and all(isinstance(x, (int, float)) for x in embedding):
        return [float(x) for x in embedding]
    return None


def _verify_voice(user_id: str, voice_sample: Any, threshold: float = 0.82) -> bool:
    """Compare provided voice embedding with stored embedding.

    Assumes voice_sample is already an embedding: List[float]. If it's not, the
    caller must pre-process with an embedding model. This keeps the module
    model-agnostic and easy to upgrade by the NLP/ASR team later.
    """
    stored = _get_stored_voice_embedding(user_id)
    if not stored:
        return False
    if not isinstance(voice_sample, list) or not all(isinstance(x, (int, float)) for x in voice_sample):
        return False
    sample_vec = [float(x) for x in voice_sample]
    score = _cosine_similarity(stored, sample_vec)
    LOGGER.info("Voice similarity for %s: %.3f", user_id, score)
    return score >= threshold


# ---------- Password utils ----------


def _get_user_password_hash(user_id: str) -> Optional[str]:
    users = _read_json(_users_db_path())
    user = users.get(user_id)
    if isinstance(user, dict):
        pw_hash = user.get("password_hash")
        if isinstance(pw_hash, str) and pw_hash:
            return pw_hash
    return None


def _verify_password(user_id: str, password: str) -> bool:
    pw_hash = _get_user_password_hash(user_id)
    if not pw_hash or not password:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), pw_hash.encode("utf-8"))
    except Exception:
        return False


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def set_user_password(user_id: str, password: str) -> None:
    users = _read_json(_users_db_path())
    record = users.get(user_id) if isinstance(users.get(user_id), dict) else {}
    record["password_hash"] = hash_password(password)
    users[user_id] = record
    _write_json(_users_db_path(), users)


# ---------- JWT tokens ----------


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _encode_jwt(payload: Dict[str, Any]) -> str:
    secret = _jwt_secret()
    return jwt.encode(payload, secret, algorithm="HS256")


def _decode_jwt(token: str) -> Dict[str, Any]:
    secret = _jwt_secret()
    return jwt.decode(token, secret, algorithms=["HS256"])  # type: ignore[no-any-return]


def _generate_tokens(user_id: str) -> Dict[str, str]:
    iat = int(time.time())
    access_exp = int((_now_utc() + timedelta(minutes=_jwt_access_ttl_minutes())).timestamp())
    refresh_exp = int((_now_utc() + timedelta(days=_jwt_refresh_ttl_days())).timestamp())

    access_payload = {"sub": user_id, "type": "access", "iat": iat, "exp": access_exp}
    refresh_payload = {"sub": user_id, "type": "refresh", "iat": iat, "exp": refresh_exp}

    access_token = _encode_jwt(access_payload)
    refresh_token = _encode_jwt(refresh_payload)
    return {"access_token": access_token, "refresh_token": refresh_token}


def refresh_session(refresh_token: str) -> Dict[str, Any]:
    try:
        payload = _decode_jwt(refresh_token)
        if payload.get("type") != "refresh":
            return {"status": "error", "message": "Invalid token type"}
        user_id = payload.get("sub")
        tokens = _generate_tokens(user_id)
        return {"status": "success", **tokens}
    except jwt.ExpiredSignatureError:
        return {"status": "error", "message": "Refresh token expired"}
    except Exception as error:
        return {"status": "error", "message": str(error)}


# ---------- Public API ----------


def authenticate_user(
    user_id: str,
    voice_sample: Optional[Any] = None,
    password: Optional[str] = None,
) -> Dict[str, Any]:
    """Authenticate a user via voice and/or password.

    - If voice_sample is provided and matches stored embedding (cosine similarity threshold), authenticate.
    - Else if password provided and matches stored bcrypt hash, authenticate.
    - Return access and refresh JWTs on success.

    voice_sample should be an embedding List[float]; generation is left to the caller.
    """
    try:
        if voice_sample is not None:
            if _verify_voice(user_id, voice_sample):
                LOGGER.success("Voice authentication succeeded for %s", user_id)
                tokens = _generate_tokens(user_id)
                _reset_failures(user_id)
                return {"status": "success", **tokens}
            else:
                LOGGER.warning("Voice authentication failed for %s", user_id)
                _record_failure(user_id)

        if password is not None:
            if _verify_password(user_id, password):
                LOGGER.success("Password authentication succeeded for %s", user_id)
                tokens = _generate_tokens(user_id)
                _reset_failures(user_id)
                return {"status": "success", **tokens}
            else:
                LOGGER.warning("Password authentication failed for %s", user_id)
                _record_failure(user_id)

        return {"status": "error", "message": "Authentication failed"}
    except Exception as error:
        LOGGER.exception("Authentication error for %s", user_id)
        return {"status": "error", "message": str(error)}


# Utilities to manage voiceprints (for enrollment/update)


def set_user_voice_embedding(user_id: str, embedding: List[float]) -> None:
    if not isinstance(embedding, list) or not all(isinstance(x, (int, float)) for x in embedding):
        raise ValueError("Embedding must be a list of numbers")
    db = _read_json(_voice_db_path())
    db[user_id] = [float(x) for x in embedding]
    _write_json(_voice_db_path(), db)


