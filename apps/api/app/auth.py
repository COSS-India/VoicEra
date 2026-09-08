"""Authentication: JWT, bcrypt password hashing, and FastAPI dependencies."""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.config import settings

logger = logging.getLogger(__name__)

security = HTTPBearer()


def _resolve_secret_key() -> str:
    if settings.SECRET_KEY:
        return settings.SECRET_KEY
    logger.warning(
        "SECRET_KEY not set in environment. Generating a temporary key. "
        "Set SECRET_KEY in .env for production!"
    )
    return secrets.token_urlsafe(32)


SECRET_KEY = _resolve_secret_key()


def _password_bytes(password: str | bytes) -> bytes:
    raw = password.encode("utf-8") if isinstance(password, str) else password
    # bcrypt has a 72-byte limit
    return raw[:72]


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against a bcrypt hash."""
    try:
        password_bytes = _password_bytes(plain_password)
        hashed_bytes = (
            hashed_password.encode("utf-8")
            if isinstance(hashed_password, str)
            else hashed_password
        )
        return bcrypt.checkpw(password_bytes, hashed_bytes)
    except Exception as exc:
        logger.error("Error verifying password: %s", exc)
        return False


def get_password_hash(password: str) -> str:
    """Hash a password with bcrypt and return the hash as a UTF-8 string."""
    password_bytes = _password_bytes(password)
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode("utf-8")


def create_access_token(
    data: dict[str, Any],
    expires_delta: timedelta | None = None,
) -> str:
    """Create a signed JWT access token."""
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    expire = now + (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire, "iat": now})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def verify_token(token: str) -> dict[str, Any] | None:
    """Decode and verify a JWT; return payload or None if invalid."""
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as exc:
        logger.warning("JWT verification failed: %s", exc)
        return None


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict[str, Any]:
    """FastAPI dependency: authenticated user from Bearer JWT."""
    payload = verify_token(credentials.credentials)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    email = payload.get("sub")
    if email is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return {
        "email": email,
        "org_id": payload.get("org_id"),
        "role": payload.get("role"),
        "exp": payload.get("exp"),
    }


async def verify_api_key(
    x_api_key: str | None = Header(None, alias="X-API-Key"),
) -> bool:
    """FastAPI dependency: verify internal service API key."""
    if not settings.INTERNAL_API_KEY:
        logger.warning("INTERNAL_API_KEY not configured. Rejecting request.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal API key not configured",
        )

    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key",
        )

    if x_api_key != settings.INTERNAL_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    return True
