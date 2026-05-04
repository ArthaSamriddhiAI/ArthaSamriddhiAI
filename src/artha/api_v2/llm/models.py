"""SmartLLMRouter ORM models — FR Entry 16.0 §4.1.

The :class:`LLMProviderConfig` table holds **one** logical row per deployment
(the "singleton" semantics). API keys are persisted as Fernet ciphertext bytes
in ``*_api_key_encrypted`` columns — never in plaintext, never in logs (per
FR 16.0 §4.1: "the router decrypts the key in memory, makes the call, and the
key never enters logs").

The cluster 1 demo treats the row as a singleton (config_id="singleton"); the
schema reserves a column-level PK so a future cluster can version the row
without a migration if audit replay needs configuration history (per the FR
note "effectively a singleton row per deployment, but versioned for audit").

Naming: per the cluster 1 strangler-fig prefix retrospective, all v2 tables
carry ``v2_``.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from artha.common.db.base import Base

# Singleton config_id used by cluster 1; reserved as a string so future
# versioning can replace it with a ULID without a schema migration.
SINGLETON_CONFIG_ID = "singleton"


class LLMProviderConfig(Base):
    """One :class:`LLMProviderConfig` row holds the deployment's LLM settings.

    Cluster 1 maintains a single row keyed by ``config_id == "singleton"``;
    a future cluster can version the row by storing a per-write ULID instead
    (the column-level PK + audit columns are already in place).
    """

    __tablename__ = "v2_llm_provider_config"

    # Identity — see SINGLETON_CONFIG_ID.
    config_id: Mapped[str] = mapped_column(String(64), primary_key=True)

    # Active provider — "mistral" | "claude" | None when un-configured.
    # Stored as a string for SQLite portability (no ENUM type).
    active_provider: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # API keys at rest: Fernet ciphertext bytes (AES-128-CBC + HMAC-SHA256
    # under the hood; see :mod:`artha.api_v2.llm.encryption`). NULL when no
    # key has been configured yet for that provider.
    mistral_api_key_encrypted: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True
    )
    claude_api_key_encrypted: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True
    )

    # Per-provider default model. The CIO can override via the settings UI.
    default_mistral_model: Mapped[str] = mapped_column(
        String(64), default="mistral-small-latest", nullable=False
    )
    default_claude_model: Mapped[str] = mapped_column(
        String(64), default="claude-sonnet-4-5-20250929", nullable=False
    )

    # Rate + timeout knobs (FR 16.0 §5).
    rate_limit_calls_per_minute: Mapped[int] = mapped_column(
        Integer, default=60, nullable=False
    )
    request_timeout_seconds: Mapped[int] = mapped_column(
        Integer, default=30, nullable=False
    )

    # Kill switch — when true, all calls fail fast with a "kill switch active"
    # error (FR 16.0 §7). The flag itself is sufficient; the *who* + *why* is
    # captured in the T1 events ``llm_kill_switch_activated`` /
    # ``llm_kill_switch_deactivated``.
    kill_switch_active: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    # Audit columns. ``updated_at`` + ``updated_by`` track the last write; the
    # T1 ledger captures the full history of changes.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_by: Mapped[str] = mapped_column(String(255), nullable=False)
