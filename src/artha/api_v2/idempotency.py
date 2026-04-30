"""Doc 2 §2.4 — `Idempotency-Key` storage + replay store.

Pass 1 ships the storage substrate. Per-endpoint wiring (the actual
"replay if seen, otherwise execute + store" flow) lands with each
mutation endpoint in subsequent passes.

Design (Stripe pattern):

  * Client supplies `Idempotency-Key` (UUID/ULID, max 64 chars) on every
    mutation request.
  * Server keys the lookup by `(firm_id, idempotency_key, method, path)`.
    Including method + path defends against the case where a single key
    is reused for two different operations — those collide on key but
    not on the full tuple, so we treat them independently.
  * Stored response (status code + body JSON) is replayed verbatim within
    24 hours. After 24 hours the entry expires.
  * `request_payload_hash` is also captured. If the same key is reused
    with a different payload, we fail closed: 422 with `idempotency-key-
    mismatch` rather than silently overwriting or replaying the old body.
    This is Stripe's behaviour and the safer default.

The replay store is its own SQLAlchemy table (`idempotency_keys`) with
indexes on `(firm_id, idempotency_key)` and `expires_at` for the
expiration sweep.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import DateTime, Index, Integer, String, Text, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from artha.common.db.base import Base
from artha.common.hashing import payload_hash

DEFAULT_TTL_HOURS = 24
MAX_KEY_LENGTH = 64


# ---------------------------------------------------------------------------
# ORM
# ---------------------------------------------------------------------------


class IdempotencyKeyRow(Base):
    """Persistence row for one idempotency-keyed mutation response.

    Indexed by `(firm_id, idempotency_key)` for the lookup hot path; a
    secondary index on `expires_at` supports the cleanup sweep.
    """

    __tablename__ = "api_v2_idempotency_keys"

    # Synthetic surrogate so we can have multiple (method, path) variants
    # under the same `(firm_id, idempotency_key)` if a client genuinely
    # reuses keys across endpoints. The lookup tuple is composed below.
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    firm_id: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(MAX_KEY_LENGTH), nullable=False)
    method: Mapped[str] = mapped_column(String(8), nullable=False)
    path: Mapped[str] = mapped_column(String(512), nullable=False)

    # Replay payload
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    # Defensive: hash of the original request payload (canonical JSON)
    request_payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    # The originating request_id (for replay-then-trace audit)
    originating_request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    __table_args__ = (
        Index(
            "ix_api_v2_idempotency_lookup",
            "firm_id", "idempotency_key", "method", "path",
            unique=True,
        ),
    )


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class IdempotencyKeyMismatchError(Exception):
    """Same key + method + path, but different request payload.

    The endpoint layer wraps this into a `ConflictError` (HTTP 409) when
    raised inside an endpoint handler.
    """


class IdempotencyStore:
    """Async repository for idempotency replay records."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        ttl_hours: int = DEFAULT_TTL_HOURS,
    ) -> None:
        self._session = session
        self._ttl_hours = ttl_hours

    # --------------------- Lookup --------------------------------

    async def lookup(
        self,
        *,
        firm_id: str,
        idempotency_key: str,
        method: str,
        path: str,
        request_payload: Any | None = None,
        as_of: datetime | None = None,
    ) -> IdempotencyKeyRow | None:
        """Return the stored row for replay, or None if no match.

        If a row exists with the same `(firm_id, key, method, path)` but
        a different `request_payload_hash`, raises
        `IdempotencyKeyMismatchError` so callers can fail closed.

        If the row exists but is expired (now > expires_at), it's treated
        as not present — the caller should execute the mutation fresh
        and call `record()` to overwrite.
        """
        as_of = as_of or self._now()
        stmt = select(IdempotencyKeyRow).where(
            IdempotencyKeyRow.firm_id == firm_id,
            IdempotencyKeyRow.idempotency_key == idempotency_key,
            IdempotencyKeyRow.method == method.upper(),
            IdempotencyKeyRow.path == path,
        )
        result = await self._session.execute(stmt)
        row = result.scalars().first()
        if row is None:
            return None
        if self._normalise_dt(row.expires_at) < as_of:
            return None

        if request_payload is not None:
            new_hash = payload_hash(self._canonicalise(request_payload))
            if row.request_payload_hash != new_hash:
                raise IdempotencyKeyMismatchError(
                    f"Idempotency-Key {idempotency_key!r} was previously used "
                    f"on {method} {path} with a different payload"
                )
        return row

    # --------------------- Record --------------------------------

    async def record(
        self,
        *,
        firm_id: str,
        idempotency_key: str,
        method: str,
        path: str,
        status_code: int,
        response_body: Any,
        request_payload: Any | None = None,
        originating_request_id: str | None = None,
        now: datetime | None = None,
    ) -> IdempotencyKeyRow:
        """Persist a mutation's response under the idempotency key.

        Overwrites any expired row for the same lookup tuple. If a non-
        expired row already exists, callers should have used `lookup()`
        first; this method assumes the slot is free.
        """
        now = now or self._now()
        existing = await self.lookup(
            firm_id=firm_id,
            idempotency_key=idempotency_key,
            method=method,
            path=path,
            as_of=now,
        )
        if existing is not None:
            # Overwrite if expired, otherwise refresh in place — the caller
            # shouldn't have re-run the mutation if a fresh entry existed.
            existing.status_code = status_code
            existing.response_body_json = json.dumps(
                response_body, sort_keys=True, separators=(",", ":")
            )
            if request_payload is not None:
                existing.request_payload_hash = payload_hash(
                    self._canonicalise(request_payload)
                )
            existing.originating_request_id = originating_request_id
            existing.created_at = now
            existing.expires_at = now + timedelta(hours=self._ttl_hours)
            await self._session.flush()
            return existing

        row = IdempotencyKeyRow(
            firm_id=firm_id,
            idempotency_key=idempotency_key,
            method=method.upper(),
            path=path,
            status_code=status_code,
            response_body_json=json.dumps(
                response_body, sort_keys=True, separators=(",", ":")
            ),
            request_payload_hash=payload_hash(
                self._canonicalise(request_payload or {})
            ),
            originating_request_id=originating_request_id,
            created_at=now,
            expires_at=now + timedelta(hours=self._ttl_hours),
        )
        self._session.add(row)
        await self._session.flush()
        return row

    # --------------------- Replay decode -------------------------

    def decode_response(self, row: IdempotencyKeyRow) -> tuple[int, Any]:
        """Read back `(status_code, body)` from a stored row."""
        return row.status_code, json.loads(row.response_body_json)

    # --------------------- Cleanup -------------------------------

    async def purge_expired(self, *, as_of: datetime | None = None) -> int:
        """Delete every expired row. Returns the number of rows removed."""
        as_of = as_of or self._now()
        stmt = select(IdempotencyKeyRow).where(
            IdempotencyKeyRow.expires_at < as_of
        )
        result = await self._session.execute(stmt)
        rows = list(result.scalars().all())
        for r in rows:
            await self._session.delete(r)
        await self._session.flush()
        return len(rows)

    # --------------------- Helpers -------------------------------

    def _canonicalise(self, payload: Any) -> dict[str, Any]:
        """Normalise the request payload to a JSON-stable dict for hashing.

        Pydantic objects → `model_dump(mode="json")`. Dicts pass through.
        Other types are wrapped under a `value` key so the hash is stable.
        """
        if hasattr(payload, "model_dump"):
            return payload.model_dump(mode="json")
        if isinstance(payload, dict):
            return payload
        return {"value": payload}

    def _normalise_dt(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value

    def _now(self) -> datetime:
        return datetime.now(UTC)


__all__ = [
    "DEFAULT_TTL_HOURS",
    "IdempotencyKeyMismatchError",
    "IdempotencyKeyRow",
    "IdempotencyStore",
    "MAX_KEY_LENGTH",
]
