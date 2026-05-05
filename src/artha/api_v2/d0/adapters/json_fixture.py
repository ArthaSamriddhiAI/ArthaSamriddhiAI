"""JSONFixtureAdapter — demo-stage adapter for cluster 3.

Loads canonical entities from a JSON fixture file (or in-memory dict, for
tests). The fixture is keyed by canonical entity type:

.. code-block:: json

   {
     "instruments": [
       {
         "isin": "INF200K01XX2",
         "amfi_scheme_code": "118989",
         "name": "SBI Bluechip Fund Direct Plan Growth",
         "short_name": "SBI Bluechip Direct G",
         "sebi_category": "large_cap",
         "amc_name": "SBI Mutual Fund",
         "issuer_name": "SBI Funds Management",
         "riskometer_label": "very_high",
         "inception_date": "2013-01-01",
         "status": "active"
       },
       ...
     ],
     "macro_snapshots": [...],
     "industry_reports": [...]
   }

The adapter:

1. Reads the fixture once per ``run()``.
2. Writes a single staging record holding the full fixture (so audit
   replay can reproduce the input deterministically).
3. For each entity in each section, derives ``asset_class`` +
   ``vehicle_type`` from the SEBI category map, falls back to literal
   ``asset_class`` + ``vehicle_type`` fields if present, or marks the row
   ``classification_confidence=low`` and emits the
   ``instrument_classification_uncertain`` T1 event.
4. Upserts via :func:`service.upsert_instrument` (chunk 3.2 only ships
   the instruments section; chunks 3.3 will add macro + industry).
5. Returns an :class:`AdapterRunResult` summarising counts.

The whole adapter is decoupled from where the fixture lives: callers
pass either a ``fixture`` dict directly (tests, in-process loading) or
``fixture_path`` pointing at a file on disk (the seed-data path used by
the demo deployment).
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from artha.api_v2.d0.adapter_base import (
    AdapterError,
    AdapterHealth,
    AdapterRunResult,
    D0Adapter,
)
from artha.api_v2.d0.event_names import INSTRUMENT_CLASSIFICATION_UNCERTAIN
from artha.api_v2.d0.instruments import sebi_mapping
from artha.api_v2.d0.instruments import service as instrument_service
from artha.api_v2.d0.staging import record_staging
from artha.api_v2.observability.t1 import emit_event


class JSONFixtureAdapter(D0Adapter):
    """Adapter that loads instruments + macro + industry sections from a
    JSON fixture.

    Source identifier convention: ``json_fixture:<fixture_name>``. A
    deployment can register multiple fixture adapters with different
    fixture names for different demo personas.
    """

    def __init__(
        self,
        *,
        fixture_name: str = "default",
        fixture: dict[str, Any] | None = None,
        fixture_path: Path | str | None = None,
        firm_id: str | None = None,
    ) -> None:
        if fixture is None and fixture_path is None:
            raise ValueError(
                "JSONFixtureAdapter requires either fixture= or fixture_path="
            )
        self._fixture_name = fixture_name
        self._fixture_path = (
            Path(fixture_path) if fixture_path is not None else None
        )
        self._fixture = fixture
        self._firm_id = firm_id
        self._last_successful_fetch_at: datetime | None = None

    # ------------------------------------------------------------------
    # D0Adapter interface
    # ------------------------------------------------------------------

    @property
    def source_identifier(self) -> str:
        return f"json_fixture:{self._fixture_name}"

    @property
    def supported_entity_types(self) -> list[str]:
        return ["Instrument"]

    async def run(
        self, db: AsyncSession, *, mode: str = "full"
    ) -> AdapterRunResult:
        run_id = str(ULID())
        started_at = datetime.now(timezone.utc)
        errors: list[AdapterError] = []
        created = 0
        updated = 0

        try:
            fixture = self._load_fixture()
        except Exception as exc:
            return AdapterRunResult(
                run_id=run_id,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
                status="failure",
                errors=[
                    AdapterError(
                        error_type="source_unavailable",
                        message=f"Could not load fixture: {exc}",
                    )
                ],
                metadata={"fixture_name": self._fixture_name, "mode": mode},
            )

        # Persist a single staging record for the whole fixture run.
        staging = await record_staging(
            db,
            source_identifier=self.source_identifier,
            adapter_run_id=run_id,
            raw_content=fixture,
            raw_content_format="json",
            source_metadata={
                "fixture_name": self._fixture_name,
                "mode": mode,
            },
            firm_id=self._firm_id,
        )

        instruments = fixture.get("instruments", []) or []
        for raw in instruments:
            try:
                normalised = self._normalise_instrument(raw, db=db)
            except _ClassificationError as exc:
                errors.append(
                    AdapterError(
                        error_type="classification_uncertain",
                        message=str(exc),
                        record_identifier=str(
                            raw.get("isin")
                            or raw.get("amfi_scheme_code")
                            or raw.get("exchange_ticker")
                            or raw.get("name", "<unknown>")
                        ),
                    )
                )
                await emit_event(
                    db,
                    event_name=INSTRUMENT_CLASSIFICATION_UNCERTAIN,
                    payload={
                        "source_identifier": self.source_identifier,
                        "adapter_run_id": run_id,
                        "raw_record": raw,
                        "error": str(exc),
                    },
                    firm_id=self._firm_id,
                )
                continue
            except Exception as exc:
                errors.append(
                    AdapterError(
                        error_type="schema_mismatch",
                        message=str(exc),
                        record_identifier=str(raw.get("name", "<unknown>")),
                    )
                )
                continue

            if mode == "validation":
                # Validation pass: count the row as if we'd write it but
                # don't actually upsert.
                created += 1
                continue

            _, was_created = await instrument_service.upsert_instrument(
                db,
                payload=normalised,
                source_identifier=self.source_identifier,
                adapter_run_id=run_id,
                staging_record_id=staging.staging_record_id,
                source_subkey=normalised.get("isin")
                or normalised.get("amfi_scheme_code"),
                firm_id=self._firm_id,
            )
            if was_created:
                created += 1
            else:
                updated += 1

        completed_at = datetime.now(timezone.utc)
        self._last_successful_fetch_at = completed_at
        status = (
            "success"
            if not errors
            else ("partial_success" if (created or updated) else "failure")
        )

        canonical_created: dict[str, int] = {"Instrument": created} if created else {}
        canonical_updated: dict[str, int] = {"Instrument": updated} if updated else {}

        return AdapterRunResult(
            run_id=run_id,
            started_at=started_at,
            completed_at=completed_at,
            status=status,
            staging_records_created=1,
            canonical_entities_created=canonical_created,
            canonical_entities_updated=canonical_updated,
            errors=errors,
            metadata={
                "fixture_name": self._fixture_name,
                "mode": mode,
                "instruments_seen": len(instruments),
            },
        )

    async def health_check(self) -> AdapterHealth:
        """For fixture adapters: healthy iff the fixture loads."""
        try:
            self._load_fixture()
        except Exception as exc:
            return AdapterHealth(
                healthy=False,
                last_successful_fetch_at=self._last_successful_fetch_at,
                error_message=str(exc),
            )
        return AdapterHealth(
            healthy=True,
            last_successful_fetch_at=self._last_successful_fetch_at,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _load_fixture(self) -> dict[str, Any]:
        if self._fixture is not None:
            return self._fixture
        assert self._fixture_path is not None  # pragma: no cover — checked in __init__
        with self._fixture_path.open("r", encoding="utf-8") as fh:
            return json.load(fh)

    def _normalise_instrument(
        self, raw: dict[str, Any], *, db: AsyncSession
    ) -> dict[str, Any]:
        """Resolve asset_class + vehicle_type from the SEBI map (or
        explicit fields), normalise dates, and return the upsert payload.
        """
        if "name" not in raw or not str(raw["name"]).strip():
            raise ValueError("Instrument record missing 'name'")

        sebi_category = raw.get("sebi_category")
        explicit_class = raw.get("asset_class")
        explicit_vehicle = raw.get("vehicle_type")

        if sebi_category and sebi_mapping.is_known(sebi_category):
            asset_class, vehicle_type = sebi_mapping.classify(sebi_category)
            classification_confidence = "high"
        elif explicit_class and explicit_vehicle:
            if explicit_class not in sebi_mapping.ASSET_CLASSES:
                raise ValueError(
                    f"Unknown asset_class {explicit_class!r}; expected one of "
                    f"{sebi_mapping.ASSET_CLASSES}"
                )
            asset_class = explicit_class
            vehicle_type = explicit_vehicle
            classification_confidence = "medium" if not sebi_category else "high"
        else:
            raise _ClassificationError(
                f"Cannot classify instrument: sebi_category="
                f"{sebi_category!r}, asset_class={explicit_class!r}, "
                f"vehicle_type={explicit_vehicle!r}"
            )

        inception = raw.get("inception_date")
        if isinstance(inception, str):
            inception = date.fromisoformat(inception)
        elif inception is not None and not isinstance(inception, date):
            raise ValueError(
                f"inception_date must be ISO date string or None; got {inception!r}"
            )

        return {
            "isin": raw.get("isin"),
            "amfi_scheme_code": raw.get("amfi_scheme_code"),
            "exchange_ticker": raw.get("exchange_ticker"),
            "name": raw["name"],
            "short_name": raw.get("short_name"),
            "asset_class": asset_class,
            "vehicle_type": vehicle_type,
            "sebi_category": (
                sebi_mapping._normalise(sebi_category)  # noqa: SLF001
                if sebi_category
                else None
            ),
            "sebi_subcategory": raw.get("sebi_subcategory"),
            "classification_confidence": classification_confidence,
            "issuer_name": raw.get("issuer_name"),
            "amc_name": raw.get("amc_name"),
            "riskometer_label": raw.get("riskometer_label"),
            "status": raw.get("status", "active"),
            "inception_date": inception,
        }


class _ClassificationError(ValueError):
    """Raised when an instrument's classification is uncertain.

    Caught inside ``run()`` so the loop can record the row as a
    classification-uncertain edge without failing the whole run.
    """
