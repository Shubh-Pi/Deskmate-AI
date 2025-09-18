import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

import jwt

from backend.services import logger as project_logger


def _get_logger():
    try:
        return project_logger.get_logger("security.session_manager")
    except Exception:
        import logging

        lg = logging.getLogger("DeskmateAI.security.session_manager")
        if not lg.handlers:
            lg.propagate = True
        return lg


LOGGER = _get_logger()


# ---------------- JWT helpers (aligned with auth.py) ----------------


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _jwt_secret() -> str:
    return os.getenv("JWT_SECRET", "change-me-secret")


def _jwt_access_ttl_minutes() -> int:
    return int(os.getenv("JWT_ACCESS_MINUTES", "30"))


def _jwt_refresh_ttl_days() -> int:
    return int(os.getenv("JWT_REFRESH_DAYS", "7"))


def _encode_jwt(payload: Dict[str, Any]) -> str:
    return jwt.encode(payload, _jwt_secret(), algorithm="HS256")


def _decode_jwt(token: str) -> Dict[str, Any]:
    return jwt.decode(token, _jwt_secret(), algorithms=["HS256"])  # type: ignore[no-any-return]


# ---------------- Session store (Redis → fallback to dict) ----------------


class _InMemoryStore:
    def __init__(self) -> None:
        self._data: Dict[str, Dict[str, str]] = {}

    def set_tokens(self, user_id: str, access: str, refresh: str) -> None:
        self._data[user_id] = {"access": access, "refresh": refresh}

    def get_tokens(self, user_id: str) -> Optional[Dict[str, str]]:
        return self._data.get(user_id)

    def clear(self, user_id: str) -> None:
        self._data.pop(user_id, None)


def _get_store():
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        return _InMemoryStore()
    try:
        import redis  # type: ignore

        client = redis.from_url(redis_url)
        # Basic ping check
        client.ping()

        class _RedisStore:
            def __init__(self, r):
                self.r = r

            def _key(self, user_id: str) -> str:
                return f"deskmate:session:{user_id}"

            def set_tokens(self, user_id: str, access: str, refresh: str) -> None:
                self.r.hset(self._key(user_id), mapping={"access": access, "refresh": refresh})

            def get_tokens(self, user_id: str) -> Optional[Dict[str, str]]:
                m = self.r.hgetall(self._key(user_id))
                if not m:
                    return None
                return {k.decode(): v.decode() for k, v in m.items()}

            def clear(self, user_id: str) -> None:
                self.r.delete(self._key(user_id))

        return _RedisStore(client)
    except Exception:
        LOGGER.debug("Redis not available; falling back to in-memory store", exc_info=True)
        return _InMemoryStore()


_STORE = _get_store()


# ---------------- Session lifecycle API ----------------


def _generate_tokens(user_id: str) -> Tuple[str, str]:
    iat = int(time.time())
    access_exp = int((_now_utc() + timedelta(minutes=_jwt_access_ttl_minutes())).timestamp())
    refresh_exp = int((_now_utc() + timedelta(days=_jwt_refresh_ttl_days())).timestamp())

    access_payload = {"sub": user_id, "type": "access", "iat": iat, "exp": access_exp}
    refresh_payload = {"sub": user_id, "type": "refresh", "iat": iat, "exp": refresh_exp}
    return _encode_jwt(access_payload), _encode_jwt(refresh_payload)


def create_session(user_id: str) -> Dict[str, Any]:
    access, refresh = _generate_tokens(user_id)
    _STORE.set_tokens(user_id, access, refresh)
    LOGGER.info("Session created for %s", user_id)
    return {"status": "success", "access_token": access, "refresh_token": refresh}


def validate_session(token: str) -> Dict[str, Any]:
    try:
        payload = _decode_jwt(token)
        if payload.get("type") != "access":
            project_logger.security_event("Invalid token type in validate_session for token")
            return {"status": "error", "message": "Invalid token type"}
        user_id = payload.get("sub")
        tokens = _STORE.get_tokens(str(user_id)) if user_id is not None else None
        if not tokens or tokens.get("access") != token:
            project_logger.security_event("Inactive/unknown session for user_id=%s", user_id)
            return {"status": "error", "message": "Session not active"}
        return {"status": "success", "user_id": user_id, "payload": payload}
    except jwt.ExpiredSignatureError:
        LOGGER.warning("Expired access token detected in validate_session")
        return {"status": "error", "message": "Access token expired"}
    except Exception as error:
        project_logger.security_event("Invalid token attempt in validate_session: {}", str(error))
        return {"status": "error", "message": str(error)}


def refresh_session(refresh_token: str) -> Dict[str, Any]:
    try:
        payload = _decode_jwt(refresh_token)
        if payload.get("type") != "refresh":
            project_logger.security_event("Invalid token type in refresh_session")
            return {"status": "error", "message": "Invalid token type"}
        user_id = payload.get("sub")
        tokens = _STORE.get_tokens(str(user_id)) if user_id is not None else None
        if not tokens or tokens.get("refresh") != refresh_token:
            project_logger.security_event("Inactive/unknown refresh session for user_id=%s", user_id)
            return {"status": "error", "message": "Session not active"}
        new_access, new_refresh = _generate_tokens(str(user_id))
        _STORE.set_tokens(str(user_id), new_access, new_refresh)
        LOGGER.info("Session refreshed for %s", user_id)
        return {"status": "success", "access_token": new_access, "refresh_token": new_refresh}
    except jwt.ExpiredSignatureError:
        LOGGER.warning("Expired refresh token in refresh_session")
        return {"status": "error", "message": "Refresh token expired"}
    except Exception as error:
        project_logger.security_event("Invalid token attempt in refresh_session: {}", str(error))
        return {"status": "error", "message": str(error)}


def end_session(user_id: str) -> Dict[str, Any]:
    _STORE.clear(user_id)
    LOGGER.info("Session ended for %s", user_id)
    return {"status": "success", "message": "Session ended"}


