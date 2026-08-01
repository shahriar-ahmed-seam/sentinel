"""Operator login and tenant API keys."""

from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..events import record_audit
from ..models import ApiKey
from ..schemas import ApiKeyCreate, ApiKeyCreated, ApiKeyOut, LoginRequest, TokenResponse
from ..security import Principal, create_access_token, mint_api_key, require_operator
from ..settings import settings

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest) -> TokenResponse:
    email_ok = hmac.compare_digest(
        payload.email.strip().lower().encode(), settings.admin_email.strip().lower().encode()
    )
    password_ok = hmac.compare_digest(payload.password.encode(), settings.admin_password.encode())
    if not (email_ok and password_ok):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    token, expires_in = create_access_token(settings.admin_email, "operator")
    return TokenResponse(
        access_token=token, expires_in=expires_in, subject=settings.admin_email, role="operator"
    )


@router.get("/me")
async def me(principal: Principal = Depends(require_operator)) -> dict[str, str]:
    return {"subject": principal.subject, "role": principal.role, "kind": principal.kind}


@router.get("/keys", response_model=list[ApiKeyOut])
async def list_keys(
    session: AsyncSession = Depends(get_session),
    _: Principal = Depends(require_operator),
) -> list[ApiKey]:
    rows = await session.execute(select(ApiKey).order_by(ApiKey.created_at.desc()))
    return list(rows.scalars())


@router.post("/keys", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED)
async def create_key(
    payload: ApiKeyCreate,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_operator),
) -> ApiKeyCreated:
    token, prefix, hashed = mint_api_key()
    key = ApiKey(
        name=payload.name,
        prefix=prefix,
        hashed=hashed,
        policy=payload.policy,
        rpm_limit=payload.rpm_limit,
        tpm_limit=payload.tpm_limit,
        monthly_budget_usd=payload.monthly_budget_usd,
    )
    session.add(key)
    await session.flush()
    await record_audit(session, actor=principal.subject, action="apikey.create", target=key.name)
    await session.commit()
    return ApiKeyCreated(**ApiKeyOut.model_validate(key).model_dump(), token=token)


@router.patch("/keys/{key_id}", response_model=ApiKeyOut)
async def update_key(
    key_id: str,
    payload: ApiKeyCreate,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_operator),
) -> ApiKey:
    key = await session.get(ApiKey, key_id)
    if key is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Key not found")
    key.name = payload.name
    key.policy = payload.policy
    key.rpm_limit = payload.rpm_limit
    key.tpm_limit = payload.tpm_limit
    key.monthly_budget_usd = payload.monthly_budget_usd
    await record_audit(session, actor=principal.subject, action="apikey.update", target=key.name)
    await session.commit()
    return key


@router.post("/keys/{key_id}/reset-spend", response_model=ApiKeyOut)
async def reset_spend(
    key_id: str,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_operator),
) -> ApiKey:
    key = await session.get(ApiKey, key_id)
    if key is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Key not found")
    previous = key.spent_usd
    key.spent_usd = 0.0
    await record_audit(
        session,
        actor=principal.subject,
        action="apikey.reset_spend",
        target=key.name,
        meta={"previous_usd": previous},
    )
    await session.commit()
    return key


@router.delete("/keys/{key_id}", response_model=ApiKeyOut)
async def revoke_key(
    key_id: str,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_operator),
) -> ApiKey:
    key = await session.get(ApiKey, key_id)
    if key is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Key not found")
    key.revoked = True
    await record_audit(session, actor=principal.subject, action="apikey.revoke", target=key.name)
    await session.commit()
    return key
