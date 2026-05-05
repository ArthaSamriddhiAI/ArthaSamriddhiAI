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
         "sebi_category": "large_cap",
         ...
       },
       ...
     ],
     "macro_snapshots": [
       {
         "country_code": "IN",
         "snapshot_period": "2026-Q1",
         "snapshot_date": "2026-03-31",
         "gdp_growth_pct": 7.2,
         "cpi_inflation_pct": 4.5,
         "repo_rate_pct": 6.5,
         "bond_yield_10y_pct": 7.1,
         "fx_usd_inr": 83.5,
         "themes": ["disinflation_underway"]
       },
       ...
     ],
     "industry_reports": [
       {
         "industry_code": "BFSI",
         "industry_name": "Banking, Financial Services and Insurance",
         "report_period": "2026-Q1",
         "report_date": "2026-03-31",
         "outlook": "positive",
         "summary": "...",
         "key_themes": ["credit_growth_normalizing"],
         "drivers": ["loan_book_expansion"],
         "risks": ["unsecured_lending_stress"]
       },
       ...
     ]
   }

Cluster 3 chunk 3.2 shipped the instruments section; chunk 3.3 adds
macro_snapshots + industry_reports. Each section is processed by its
own helper, allowing chunks 3.3+ to add sections without bloating the
adapter's ``run()`` body.

The adapter:

1. Reads the fixture once per ``run()``.
2. Writes a single staging record holding the full fixture (so audit
   replay can reproduce the input deterministically).
3. Processes each section in turn — instrument classification edge cases
   land in errors but don't fail the whole run; missing-required-field
   schema mismatches land in errors with ``error_type="schema_mismatch"``.
4. Returns an :class:`AdapterRunResult` summarising counts.
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
from artha.api_v2.d0.adapters import multi_source
from artha.api_v2.d0.event_names import INSTRUMENT_CLASSIFICATION_UNCERTAIN
from artha.api_v2.d0.industry import service as industry_service
from artha.api_v2.d0.instruments import sebi_mapping
from artha.api_v2.d0.instruments import service as instrument_service
from artha.api_v2.d0.macro import service as macro_service
from artha.api_v2.d0.staging import record_staging
from artha.api_v2.observability.t1 import emit_event


class JSONFixtureAdapter(D0Adapter):
    """Adapter that loads instruments + macro + industry sections from a
    JSON fixture.

    Source identifier convention: ``json_fixture:<fixture_name>``.
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
        return ["Instrument", "MacroSnapshot", "IndustryReport"]

    async def run(
        self, db: AsyncSession, *, mode: str = "full"
    ) -> AdapterRunResult:
        run_id = str(ULID())
        started_at = datetime.now(timezone.utc)
        errors: list[AdapterError] = []
        created: dict[str, int] = {}
        updated: dict[str, int] = {}

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
        # The RAW fixture is staged (not the flattened sectioned shape) so
        # audit replay can reproduce the input deterministically.
        staging = await record_staging(
            db,
            source_identifier=self.source_identifier,
            adapter_run_id=run_id,
            raw_content=fixture,
            raw_content_format="json",
            source_metadata={
                "fixture_name": self._fixture_name,
                "mode": mode,
                "shape": (
                    "multi_source"
                    if multi_source.is_multi_source_fixture(fixture)
                    else "sectioned"
                ),
            },
            firm_id=self._firm_id,
        )

        # Cluster 3 addendum: when the fixture is the merged Kush-shape
        # multi-source JSON, transform it into the canonical sectioned
        # shape before iterating per section. The original raw fixture
        # remains staged above for audit replay.
        if multi_source.is_multi_source_fixture(fixture):
            sectioned = multi_source.flatten_multi_source(fixture)
        else:
            sectioned = fixture

        # ----- Section: instruments -----
        i_created, i_updated = await self._process_instruments(
            sectioned.get("instruments", []) or [],
            db=db,
            run_id=run_id,
            staging_id=staging.staging_record_id,
            mode=mode,
            errors=errors,
        )
        if i_created:
            created["Instrument"] = i_created
        if i_updated:
            updated["Instrument"] = i_updated

        # ----- Section: macro_snapshots -----
        m_created, m_updated = await self._process_macro_snapshots(
            sectioned.get("macro_snapshots", []) or [],
            db=db,
            run_id=run_id,
            staging_id=staging.staging_record_id,
            mode=mode,
            errors=errors,
        )
        if m_created:
            created["MacroSnapshot"] = m_created
        if m_updated:
            updated["MacroSnapshot"] = m_updated

        # ----- Section: industry_reports -----
        r_created, r_updated = await self._process_industry_reports(
            sectioned.get("industry_reports", []) or [],
            db=db,
            run_id=run_id,
            staging_id=staging.staging_record_id,
            mode=mode,
            errors=errors,
        )
        if r_created:
            created["IndustryReport"] = r_created
        if r_updated:
            updated["IndustryReport"] = r_updated

        completed_at = datetime.now(timezone.utc)
        self._last_successful_fetch_at = completed_at
        any_writes = any(created.values()) or any(updated.values())
        status = (
            "success"
            if not errors
            else ("partial_success" if any_writes else "failure")
        )

        return AdapterRunResult(
            run_id=run_id,
            started_at=started_at,
            completed_at=completed_at,
            status=status,
            staging_records_created=1,
            canonical_entities_created=created,
            canonical_entities_updated=updated,
            errors=errors,
            metadata={
                "fixture_name": self._fixture_name,
                "mode": mode,
                "instruments_seen": len(
                    sectioned.get("instruments", []) or []
                ),
                "macro_snapshots_seen": len(
                    sectioned.get("macro_snapshots", []) or []
                ),
                "industry_reports_seen": len(
                    sectioned.get("industry_reports", []) or []
                ),
                "fixture_shape": (
                    "multi_source"
                    if multi_source.is_multi_source_fixture(fixture)
                    else "sectioned"
                ),
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
    # Section processors
    # ------------------------------------------------------------------

    async def _process_instruments(
        self,
        rows: list[dict[str, Any]],
        *,
        db: AsyncSession,
        run_id: str,
        staging_id: str,
        mode: str,
        errors: list[AdapterError],
    ) -> tuple[int, int]:
        created = 0
        updated = 0
        for raw in rows:
            try:
                normalised = self._normalise_instrument(raw)
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
                created += 1
                continue

            _, was_created = await instrument_service.upsert_instrument(
                db,
                payload=normalised,
                source_identifier=self.source_identifier,
                adapter_run_id=run_id,
                staging_record_id=staging_id,
                source_subkey=normalised.get("isin")
                or normalised.get("amfi_scheme_code"),
                firm_id=self._firm_id,
            )
            if was_created:
                created += 1
            else:
                updated += 1
        return created, updated

    async def _process_macro_snapshots(
        self,
        rows: list[dict[str, Any]],
        *,
        db: AsyncSession,
        run_id: str,
        staging_id: str,
        mode: str,
        errors: list[AdapterError],
    ) -> tuple[int, int]:
        created = 0
        updated = 0
        for raw in rows:
            for required in ("country_code", "snapshot_period", "snapshot_date"):
                if required not in raw:
                    errors.append(
                        AdapterError(
                            error_type="schema_mismatch",
                            message=(
                                f"MacroSnapshot record missing required "
                                f"field {required!r}"
                            ),
                            record_identifier=str(
                                raw.get("snapshot_period", "<unknown>")
                            ),
                        )
                    )
                    break
            else:
                if mode == "validation":
                    created += 1
                    continue
                _, was_created = await macro_service.upsert_macro_snapshot(
                    db,
                    payload=raw,
                    source_identifier=self.source_identifier,
                    adapter_run_id=run_id,
                    staging_record_id=staging_id,
                    source_subkey=(
                        f"{raw['country_code']}:{raw['snapshot_period']}"
                    ),
                    firm_id=self._firm_id,
                )
                if was_created:
                    created += 1
                else:
                    updated += 1
        return created, updated

    async def _process_industry_reports(
        self,
        rows: list[dict[str, Any]],
        *,
        db: AsyncSession,
        run_id: str,
        staging_id: str,
        mode: str,
        errors: list[AdapterError],
    ) -> tuple[int, int]:
        created = 0
        updated = 0
        for raw in rows:
            missing = [
                f
                for f in (
                    "industry_code",
                    "industry_name",
                    "report_period",
                    "report_date",
                    "outlook",
                    "summary",
                )
                if f not in raw
            ]
            if missing:
                errors.append(
                    AdapterError(
                        error_type="schema_mismatch",
                        message=(
                            f"IndustryReport record missing required "
                            f"fields: {missing}"
                        ),
                        record_identifier=str(
                            raw.get("industry_code", "<unknown>")
                        ),
                    )
                )
                continue
            try:
                if mode == "validation":
                    # Even in validation mode we want to surface invalid
                    # outlook values; service.upsert validates so call it
                    # but discard via a try/raise — simpler: validate inline.
                    if raw["outlook"] not in industry_service.VALID_OUTLOOKS:
                        raise ValueError(
                            f"Unknown outlook {raw['outlook']!r}"
                        )
                    created += 1
                    continue
                _, was_created = await industry_service.upsert_industry_report(
                    db,
                    payload=raw,
                    source_identifier=self.source_identifier,
                    adapter_run_id=run_id,
                    staging_record_id=staging_id,
                    source_subkey=(
                        f"{raw['industry_code']}:{raw['report_period']}"
                    ),
                    firm_id=self._firm_id,
                )
                if was_created:
                    created += 1
                else:
                    updated += 1
            except ValueError as exc:
                errors.append(
                    AdapterError(
                        error_type="schema_mismatch",
                        message=str(exc),
                        record_identifier=str(
                            raw.get("industry_code", "<unknown>")
                        ),
                    )
                )
        return created, updated

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
        self, raw: dict[str, Any]
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
