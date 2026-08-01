"""Runtime-editable gateway policy.

Environment variables seed the defaults; the operator console can change these
without a redeploy. The hot path reads this object, so a toggle takes effect on
the next request rather than the next deployment.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .models import PlatformConfig
from .settings import settings

log = logging.getLogger("sentinel.runtime")
CONFIG_KEY = "gateway_policy"


@dataclass
class RuntimeConfig:
    cache_enabled: bool = settings.cache_enabled
    cache_ttl_seconds: int = settings.cache_ttl_seconds
    cache_max_temperature: float = settings.cache_max_temperature
    tracing_enabled: bool = settings.tracing_enabled
    default_rpm_limit: int = settings.default_rpm_limit
    default_tpm_limit: int = settings.default_tpm_limit
    max_attempts: int = settings.max_attempts
    circuit_failure_threshold: int = settings.circuit_failure_threshold
    circuit_reset_seconds: int = settings.circuit_reset_seconds
    slo_ttft_ms: float = settings.slo_ttft_ms
    slo_availability: float = settings.slo_availability
    redact_pii: bool = True

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def apply(self, updates: dict[str, Any]) -> None:
        for key, value in updates.items():
            if value is None or not hasattr(self, key):
                continue
            setattr(self, key, value)


config = RuntimeConfig()


async def load(session: AsyncSession) -> RuntimeConfig:
    row = await session.get(PlatformConfig, CONFIG_KEY)
    if row is not None and isinstance(row.value, dict):
        config.apply(row.value)
    return config


async def save(session: AsyncSession, updates: dict[str, Any]) -> RuntimeConfig:
    config.apply(updates)
    row = await session.get(PlatformConfig, CONFIG_KEY)
    if row is None:
        session.add(PlatformConfig(key=CONFIG_KEY, value=config.as_dict()))
    else:
        row.value = config.as_dict()
    await session.flush()
    log.info("runtime policy updated: %s", ", ".join(sorted(updates)))
    return config
