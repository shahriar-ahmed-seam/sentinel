"""Runtime configuration for the Sentinel gateway."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        protected_namespaces=(),
    )

    # --- identity -----------------------------------------------------------
    app_name: str = "Sentinel"
    app_env: Literal["local", "staging", "production"] = "local"
    app_version: str = "1.0.0"
    git_sha: str = "dev"
    log_level: str = "INFO"
    region: str = "local"

    # --- persistence --------------------------------------------------------
    database_url: str = ""
    db_pool_size: int = 5
    db_max_overflow: int = 5

    # --- auth ---------------------------------------------------------------
    jwt_secret: str = "change-me-in-production"
    jwt_ttl_minutes: int = 720
    admin_email: str = "admin@sentinel.dev"
    admin_password: str = "sentinel"
    public_read: bool = True
    cors_origins: str = "*"
    # Allow the data plane without a key (demo only). Keys are always accepted.
    allow_anonymous_inference: bool = True

    # --- upstream providers -------------------------------------------------
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    # Any OpenAI-compatible endpoint: Ollama, vLLM, Groq, Together, OpenRouter.
    compat_api_key: str = ""
    compat_base_url: str = ""
    compat_label: str = "openai-compatible"

    upstream_timeout_seconds: float = 90.0
    upstream_connect_timeout_seconds: float = 8.0
    max_attempts: int = 3
    retry_base_delay_ms: int = 220

    # --- resilience ---------------------------------------------------------
    circuit_failure_threshold: int = 5
    circuit_reset_seconds: int = 30
    circuit_half_open_probes: int = 2

    # --- limits -------------------------------------------------------------
    default_rpm_limit: int = 240
    default_tpm_limit: int = 240_000
    default_monthly_budget_usd: float = 25.0
    max_prompt_chars: int = 120_000
    max_output_tokens_cap: int = 8192
    max_concurrency: int = 64

    # --- caching ------------------------------------------------------------
    cache_enabled: bool = True
    cache_ttl_seconds: int = 3600
    # Only deterministic-ish calls are cached unless the caller opts in.
    cache_max_temperature: float = 0.25
    cache_max_entries: int = 20_000

    # --- observability ------------------------------------------------------
    tracing_enabled: bool = True
    trace_retention_hours: int = 72
    request_retention_days: int = 14
    # Set to an OTLP/HTTP collector to mirror spans out (optional dependency).
    otel_exporter_otlp_endpoint: str = ""
    otel_service_name: str = "sentinel-gateway"
    slo_ttft_ms: float = 1500.0
    slo_availability: float = 0.995

    # --- demo ---------------------------------------------------------------
    bootstrap_demo: bool = True
    simulate_only: bool = False

    @field_validator("database_url")
    @classmethod
    def _normalise_database_url(cls, value: str) -> str:
        value = (value or "").strip()
        if not value:
            return ""
        if value.startswith("postgres://"):
            value = "postgresql://" + value[len("postgres://") :]
        if value.startswith("postgresql://"):
            value = "postgresql+psycopg://" + value[len("postgresql://") :]
        if value.startswith("sqlite://") and "+aiosqlite" not in value:
            value = value.replace("sqlite://", "sqlite+aiosqlite://", 1)
        return value

    @property
    def sqlalchemy_url(self) -> str:
        if self.database_url:
            return self.database_url
        path = REPO_ROOT / ".data" / "sentinel.db"
        path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite+aiosqlite:///{path.as_posix()}"

    @property
    def is_postgres(self) -> bool:
        return self.sqlalchemy_url.startswith("postgresql")

    @property
    def cors_origin_list(self) -> list[str]:
        raw = (self.cors_origins or "").strip()
        if raw in ("", "*"):
            return ["*"]
        return [origin.strip() for origin in raw.split(",") if origin.strip()]

    @property
    def live_providers(self) -> list[str]:
        """Upstreams with credentials present."""
        if self.simulate_only:
            return []
        live = []
        if self.deepseek_api_key:
            live.append("deepseek")
        if self.openai_api_key:
            live.append("openai")
        if self.compat_api_key and self.compat_base_url:
            live.append("compat")
        return live


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
