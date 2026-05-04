from __future__ import annotations

from enum import Enum

from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class LLMProviderName(str, Enum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    MISTRAL = "mistral"
    MOCK = "mock"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = "sqlite+aiosqlite:///./artha.db"

    # LLM
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    mistral_api_key: str = ""
    default_llm_provider: LLMProviderName = LLMProviderName.MOCK

    # Application
    log_level: str = "INFO"
    environment: Environment = Environment.DEVELOPMENT

    # Orchestrator
    max_orchestrator_loops: int = 3
    default_llm_temperature: float = 0.0

    # Kill switch
    execution_enabled: bool = True

    # ---------------- Cluster 0: Authentication & Sessions ----------------
    # Per FR Entry 17.0 §3.1, FR Entry 17.1 §2, and the Cluster 0 Dev-Mode Addendum.
    #
    # JWT signing key. HS256 by default; RS256 supported when key rotation matters
    # in production (FR 17.1 §2.1). If left empty in DEVELOPMENT, a random secret
    # is generated at startup (tokens become invalid across restarts; acceptable for dev).
    # MUST be set explicitly for non-development environments.
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "samriddhi-backend"
    jwt_audience: str = "samriddhi-app"
    jwt_access_token_minutes: int = 15

    # Refresh cookie attributes per FR 17.1 §2.2. Max-Age 8 hours = 28800 seconds.
    refresh_cookie_max_age_seconds: int = 8 * 60 * 60
    refresh_cookie_path: str = "/api/v2/auth/refresh"
    # When None, the effective value derives from environment: True for non-dev,
    # False for dev (so cookies work over plain HTTP on localhost).
    refresh_cookie_secure_override: bool | None = None

    # Default per-user concurrent session limit (FR 17.1 §2.6).
    max_concurrent_sessions_per_user: int = 3

    # Path to the YAML defining the demo firm + 4 test users used by the
    # stub /api/v2/auth/dev-login endpoint (Dev-Mode Addendum §3.1).
    dev_test_users_path: str = "dev/test_users.yaml"

    # ---------------- Cluster 0: SSE Channel ----------------
    # Per FR Entry 18.0.
    #
    # Heartbeat interval (FR 18.0 §2.4). 30s default per spec; configurable
    # for tests / for deployments behind picky proxies.
    sse_heartbeat_interval_seconds: int = 30

    # Lead time before access JWT expiry to emit token_refresh_required
    # (FR 18.0 §2.7). 60s default per spec.
    sse_token_refresh_lead_seconds: int = 60

    # Per-connection replay buffer window (FR 18.0 §2.5). 5 minutes default.
    sse_buffer_window_seconds: int = 5 * 60

    # Per-event payload size cap. Carried in connection_established so the
    # client knows the contract; not yet enforced in cluster 0 (no events
    # outside connection lifecycle fire).
    sse_max_payload_bytes: int = 65536

    # Per-connection event-emission rate limit (FR 18.0 §7.3). 600/min default.
    # Not yet enforced in cluster 0; carried as configuration for forward use.
    sse_max_events_per_minute: int = 600

    # ---------------- Cluster 1 chunk 1.3: SmartLLMRouter ----------------
    # Per FR Entry 16.0 §4.1.
    #
    # The deployment-level Fernet key used to wrap LLM provider API keys at
    # rest. MUST be a urlsafe-base64-encoded 32-byte key (the format
    # ``cryptography.fernet.Fernet.generate_key()`` produces). When empty in
    # DEVELOPMENT a per-process random key is generated lazily; ciphertext
    # written under that key is unreadable across restarts (acceptable for
    # local demos). MUST be set explicitly for non-development environments.
    samriddhi_encryption_key: str = ""

    # Default rate limit for the SmartLLMRouter when no DB row exists yet.
    # Cluster 1 hardcodes 60 calls/minute per FR 16.0 §5.1.
    llm_router_default_rate_limit_per_minute: int = 60
    llm_router_default_timeout_seconds: int = 30

    @property
    def refresh_cookie_secure(self) -> bool:
        """Effective `Secure` flag for the refresh cookie."""
        if self.refresh_cookie_secure_override is not None:
            return self.refresh_cookie_secure_override
        return self.environment != Environment.DEVELOPMENT


settings = Settings()
