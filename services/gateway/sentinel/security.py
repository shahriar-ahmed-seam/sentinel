"""Operator JWT for the control plane, hashed keys for the data plane."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_session
from .models import ApiKey
from .settings import settings

ALGORITHM = "HS256"
_PBKDF_ROUNDS = 120_000
KEY_PREFIX = "sk-sent-"
bearer = HTTPBearer(auto_error=False)


def hash_secret(secret: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(8)
    digest = hashlib.pbkdf2_hmac("sha256", secret.encode(), salt.encode(), _PBKDF_ROUNDS)
    return f"{salt}${digest.hex()}"


def verify_secret(secret: str, hashed: str) -> bool:
    try:
        salt, _ = hashed.split("$", 1)
    except ValueError:
        return False
    return hmac.compare_digest(hash_secret(secret, salt), hashed)


def create_access_token(subject: str, role: str = "operator") -> tuple[str, int]:
    expires_in = settings.jwt_ttl_minutes * 60
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
        "iss": "sentinel",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM), expires_in


def decode_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM], issuer="sentinel")


class Principal:
    def __init__(
        self,
        subject: str,
        role: str,
        *,
        kind: str = "user",
        key: ApiKey | None = None,
    ) -> None:
        self.subject = subject
        self.role = role
        self.kind = kind
        self.key = key

    @property
    def key_id(self) -> str | None:
        return self.key.id if self.key else None

    def __repr__(self) -> str:  # pragma: no cover
        return f"Principal({self.subject!r}, {self.role!r})"


ANONYMOUS = Principal("anonymous", "anonymous", kind="anonymous")


def _operator_from_request(request: Request) -> Principal | None:
    auth = request.headers.get("authorization") or ""
    if not auth.lower().startswith("bearer "):
        return None
    raw = auth.split(" ", 1)[1].strip()
    if raw.startswith(KEY_PREFIX):
        return None
    try:
        claims = decode_token(raw)
    except jwt.PyJWTError:
        return None
    return Principal(claims.get("sub", "unknown"), claims.get("role", "operator"))


async def require_operator(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> Principal:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    try:
        claims = decode_token(credentials.credentials)
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token expired") from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from exc
    return Principal(claims.get("sub", "unknown"), claims.get("role", "operator"))


async def allow_read(request: Request) -> Principal:
    principal = _operator_from_request(request)
    if principal:
        return principal
    if settings.public_read:
        return ANONYMOUS
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")


# --------------------------------------------------------------------------- #
# data plane keys
# --------------------------------------------------------------------------- #
def mint_api_key() -> tuple[str, str, str]:
    token = f"{KEY_PREFIX}{secrets.token_urlsafe(28)}"
    return token, token[:14], hash_secret(token)


def _extract_key(request: Request) -> str:
    for header in ("x-api-key", "api-key"):
        value = request.headers.get(header)
        if value:
            return value.strip()
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return ""


async def resolve_caller(request: Request, session: AsyncSession) -> Principal:
    """Accept a service key, an operator token, or anonymous when permitted."""
    token = _extract_key(request)

    if token and not token.startswith(KEY_PREFIX):
        try:
            claims = decode_token(token)
            return Principal(claims.get("sub", "operator"), "operator", kind="user")
        except jwt.PyJWTError:
            pass

    if token.startswith(KEY_PREFIX):
        rows = (
            await session.execute(
                select(ApiKey).where(ApiKey.prefix == token[:14], ApiKey.revoked.is_(False))
            )
        ).scalars()
        for row in rows:
            if verify_secret(token, row.hashed):
                return Principal(row.name, "service", kind="api_key", key=row)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key")

    if settings.allow_anonymous_inference:
        return ANONYMOUS
    raise HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Missing API key. Send it as `Authorization: Bearer sk-sent-...` or `X-API-Key`.",
    )


async def require_caller(
    request: Request, session: AsyncSession = Depends(get_session)
) -> Principal:
    return await resolve_caller(request, session)
