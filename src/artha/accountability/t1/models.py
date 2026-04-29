"""Canonical T1 event (Section 15.11.1)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from artha.common.hashing import payload_hash as compute_payload_hash
from artha.common.standards import T1EventType
from artha.common.types import VersionPins
from artha.common.ulid import is_ulid, new_ulid


class T1Event(BaseModel):
    """An immutable event in the decision telemetry bus (Section 15.11.1).

    Append-only: once committed, no field may change. Corrections appear as new
    events with `correction_of` referencing the corrected event's `event_id`.
    Replay reconstructs cases bit-identically given the event log plus the
    `version_pins` captured per event.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Identity
    event_id: str = Field(default_factory=new_ulid, description="ULID; time-sortable")
    event_type: T1EventType
    timestamp: datetime

    # Scope (firm is required; case/client/advisor are nullable for system-level events)
    firm_id: str
    case_id: str | None = None
    client_id: str | None = None
    advisor_id: str | None = None

    # Payload + integrity
    payload: dict[str, Any] = Field(default_factory=dict)
    payload_hash: str = Field(description="SHA-256 hex of canonical JSON of payload")

    # Versioning + replay
    version_pins: VersionPins = Field(default_factory=VersionPins)

    # Correction chain (append-only; corrections are new rows, not in-place edits)
    correction_of: str | None = None

    @field_validator("event_id")
    @classmethod
    def _check_event_id(cls, v: str) -> str:
        if not is_ulid(v):
            raise ValueError(f"event_id must be a 26-char Crockford base32 ULID, got {v!r}")
        return v

    @field_validator("correction_of")
    @classmethod
    def _check_correction_of(cls, v: str | None) -> str | None:
        if v is not None and not is_ulid(v):
            raise ValueError(f"correction_of must be a ULID when set, got {v!r}")
        return v

    @field_validator("payload_hash")
    @classmethod
    def _check_payload_hash_shape(cls, v: str) -> str:
        if len(v) != 64 or not all(c in "0123456789abcdef" for c in v):
            raise ValueError(f"payload_hash must be 64-char lowercase hex SHA-256, got {v!r}")
        return v

    @classmethod
    def build(
        cls,
        *,
        event_type: T1EventType,
        firm_id: str,
        timestamp: datetime,
        payload: dict[str, Any] | None = None,
        case_id: str | None = None,
        client_id: str | None = None,
        advisor_id: str | None = None,
        version_pins: VersionPins | None = None,
        correction_of: str | None = None,
        event_id: str | None = None,
    ) -> T1Event:
        """Construct a T1Event with payload_hash computed from `payload`.

        Convenience over the raw constructor — callers shouldn't have to compute
        the hash separately, since the spec requires it to be derived from the
        canonical JSON of the payload.
        """
        actual_payload = payload or {}
        return cls(
            event_id=event_id or new_ulid(),
            event_type=event_type,
            timestamp=timestamp,
            firm_id=firm_id,
            case_id=case_id,
            client_id=client_id,
            advisor_id=advisor_id,
            payload=actual_payload,
            payload_hash=compute_payload_hash(actual_payload),
            version_pins=version_pins or VersionPins(),
            correction_of=correction_of,
        )

    def verify_payload_integrity(self) -> bool:
        """Re-hash payload and compare against stored hash. Tamper detector."""
        return compute_payload_hash(self.payload) == self.payload_hash
