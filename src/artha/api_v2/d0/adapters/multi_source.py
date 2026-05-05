"""Per-source loaders for the cluster 3 addendum merged JSON fixture.

The cluster 3 addendum (Kush Goyal's merged JSON,
``data/fixtures/SamriddhiAI_data_merged.json``) brings 7 distinct
source shapes into one file:

- ``nifty500_fundamentals.json`` (500 listed equities)
- ``SAMRIDDHI_MF_Database.json`` (46 SEBI MF categories with schemes)
- ``pms_full_513_funds.json`` (513 PMS funds)
- ``AIF_Extracted_Data_Mar2026.json`` (162 AIF profiles)
- ``Macro_Data_Snapshot.json`` (1 macro snapshot, 5 dimensions)
- 14 ``Industry data (JSON)/*.json`` files (PDF text dumps)
- 100 ``Unlisted Equity/*.json`` files (private companies)

The chunk-3.2 JSONFixtureAdapter expected pre-bucketed
``instruments``/``macro_snapshots``/``industry_reports`` arrays. Rather
than maintain two adapter classes, we keep one adapter and add a
detection + flatten step here: when the adapter sees the multi-source
shape it transforms it in-memory into the canonical sectioned shape
before running the existing per-section processors.

The original raw fixture is still preserved in the staging record (so
audit replay reproduces the input deterministically) — flattening
happens AFTER staging, before canonical-entity writes.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date as date_t
from datetime import datetime as datetime_t
from typing import Any

from artha.api_v2.d0.instruments import sebi_mapping

# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


_MULTI_SOURCE_SENTINEL_KEYS: tuple[str, ...] = (
    "nifty500_fundamentals.json",
    "SAMRIDDHI_MF_Database.json",
    "pms_full_513_funds.json",
    "AIF_Extracted_Data_Mar2026.json",
    "Macro_Data_Snapshot.json",
)


def is_multi_source_fixture(fixture: dict[str, Any]) -> bool:
    """True if the fixture is the cluster 3 addendum merged JSON.

    Detection is based on the presence of any of the well-known top-level
    keys produced by the merging script. Any single hit is sufficient —
    partial fixtures (e.g. just instruments + macro, no industry) still
    classify as multi-source.
    """
    keys = set(fixture.keys())
    if any(k.startswith("Industry data (JSON)") for k in keys):
        return True
    if any(k.startswith("Unlisted Equity/") for k in keys):
        return True
    return any(root in keys for root in _MULTI_SOURCE_SENTINEL_KEYS)


# ---------------------------------------------------------------------------
# Top-level orchestrator
# ---------------------------------------------------------------------------


def flatten_multi_source(fixture: dict[str, Any]) -> dict[str, Any]:
    """Convert the merged JSON shape into the canonical sectioned shape.

    Returns a dict with three keys: ``instruments``, ``macro_snapshots``,
    ``industry_reports``. Records that fail their per-source mapper are
    silently skipped — the caller (the JSONFixtureAdapter) catches
    schema/classification failures via the existing per-section error
    paths once the records reach the upsert helpers.
    """
    instruments: list[dict[str, Any]] = []
    macro_snapshots: list[dict[str, Any]] = []
    industry_reports: list[dict[str, Any]] = []

    if "nifty500_fundamentals.json" in fixture:
        instruments.extend(load_nifty500(fixture["nifty500_fundamentals.json"]))
    if "SAMRIDDHI_MF_Database.json" in fixture:
        instruments.extend(load_mf_database(fixture["SAMRIDDHI_MF_Database.json"]))
    if "pms_full_513_funds.json" in fixture:
        instruments.extend(load_pms(fixture["pms_full_513_funds.json"]))
    if "AIF_Extracted_Data_Mar2026.json" in fixture:
        instruments.extend(load_aif(fixture["AIF_Extracted_Data_Mar2026.json"]))

    for k, v in fixture.items():
        if k.startswith("Unlisted Equity/") and isinstance(v, dict):
            row = load_unlisted(k, v)
            if row is not None:
                instruments.append(row)
        elif k.startswith("Industry data (JSON)/") and isinstance(v, dict):
            industry_reports.append(load_industry(k, v))

    if "Macro_Data_Snapshot.json" in fixture:
        macro_snapshots.append(load_macro(fixture["Macro_Data_Snapshot.json"]))

    return {
        "instruments": instruments,
        "macro_snapshots": macro_snapshots,
        "industry_reports": industry_reports,
    }


# ---------------------------------------------------------------------------
# Per-source instrument loaders
# ---------------------------------------------------------------------------


def load_nifty500(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Map Nifty500 ``companies`` → instrument dicts (equity stocks)."""
    out: list[dict[str, Any]] = []
    for co in data.get("companies", []) or []:
        name = co.get("name")
        if not name or not str(name).strip():
            continue
        out.append(
            {
                "name": str(name)[:255],
                "exchange_ticker": _synthetic_ticker("nse", str(name)),
                "asset_class": "equity",
                "vehicle_type": "stock",
                "classification_confidence": "medium",
                "status": "active",
            }
        )
    return out


def load_mf_database(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Map SAMRIDDHI MF Database (46 category lists of schemes) → instruments."""
    out: list[dict[str, Any]] = []
    for category_label, schemes in data.items():
        if not isinstance(schemes, list):
            continue
        for scheme in schemes:
            name = scheme.get("Fund Name")
            if not name or not str(name).strip():
                continue
            scheme_category = scheme.get("SEBI Category") or category_label
            isin = scheme.get("ISIN")
            amfi_code = scheme.get("AMFI Code")

            try:
                asset_class, vehicle_type = sebi_mapping.classify(scheme_category)
                sebi_canonical = sebi_mapping.to_canonical_key(scheme_category)
                classification_confidence = "high"
            except sebi_mapping.UnknownSebiCategoryError:
                # Fall back to category-label classification + parent
                # asset class hint from the scheme record.
                parent_class = (scheme.get("Asset Class") or "").lower()
                if parent_class in sebi_mapping.ASSET_CLASSES:
                    asset_class = parent_class
                else:
                    asset_class = "equity"
                vehicle_type = (
                    "etf" if "etf" in str(category_label).lower() else "mutual_fund"
                )
                sebi_canonical = sebi_mapping.to_canonical_key(category_label)
                classification_confidence = "low"

            out.append(
                {
                    "isin": str(isin)[:12] if isin else None,
                    "amfi_scheme_code": (
                        str(amfi_code)[:20] if amfi_code is not None else None
                    ),
                    "name": str(name)[:255],
                    "asset_class": asset_class,
                    "vehicle_type": vehicle_type,
                    "sebi_category": sebi_canonical,
                    "classification_confidence": classification_confidence,
                    "amc_name": _amc_from_name(str(name)),
                    "status": "active",
                }
            )
    return out


def load_pms(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Map PMS Bazaar ``funds`` → instrument dicts (vehicle_type=pms)."""
    out: list[dict[str, Any]] = []
    for fund in data.get("funds", []) or []:
        identity = fund.get("identity") or {}
        name = identity.get("fund_name")
        if not name or not str(name).strip():
            continue
        strategy = (identity.get("strategy_type") or "").lower()
        if strategy not in sebi_mapping.ASSET_CLASSES:
            strategy = "equity"
        # PMS funds have no ISIN / AMFI / ticker — synthesise a stable
        # exchange_ticker from name + manager so re-runs upsert by identity.
        manager = identity.get("fund_manager") or ""
        synthetic_id = _synthetic_ticker("pms", str(name), str(manager))
        out.append(
            {
                "name": str(name)[:255],
                "exchange_ticker": synthetic_id,
                "asset_class": strategy,
                "vehicle_type": "pms",
                "classification_confidence": "medium",
                "amc_name": str(manager)[:255] if manager else None,
                "status": "active",
                "inception_date": _parse_loose_date(identity.get("inception_date")),
            }
        )
    return out


def load_aif(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Map AIF ``Fund Profiles`` → instrument dicts (vehicle_type=aif)."""
    out: list[dict[str, Any]] = []
    for profile in data.get("Fund Profiles", []) or []:
        name = profile.get("Fund Name")
        if not name or not str(name).strip():
            continue
        manager = profile.get("AMC / Investment Manager") or ""
        synthetic_id = _synthetic_ticker("aif", str(name), str(manager))
        out.append(
            {
                "name": str(name)[:255],
                "exchange_ticker": synthetic_id,
                "asset_class": "alternatives",
                "vehicle_type": "aif",
                "sebi_subcategory": str(profile.get("SEBI Category") or "")[:80]
                or None,
                "classification_confidence": "medium",
                "amc_name": str(manager)[:255] if manager else None,
                "status": "active",
            }
        )
    return out


def load_unlisted(key: str, data: dict[str, Any]) -> dict[str, Any] | None:
    """Map one Unlisted Equity company JSON → an instrument dict."""
    identity = data.get("identity") or {}
    name = identity.get("name")
    if not name or not str(name).strip():
        return None
    company_id = identity.get("company_id") or _slug(str(name))
    # company_id from the source is already short (slug-form), but enforce
    # uniqueness via the same hash-tail strategy used for PMS/AIF.
    ticker = _synthetic_ticker("uneq", str(company_id))
    raw_status = (identity.get("status") or "active").lower()
    status = raw_status if raw_status in {"active", "suspended", "delisted"} else "active"
    return {
        "name": str(name)[:255],
        "exchange_ticker": ticker,
        "asset_class": "equity",
        "vehicle_type": "unlisted_equity",
        "classification_confidence": "medium",
        "status": status,
        "inception_date": _parse_loose_date(identity.get("incorporation_date")),
    }


# ---------------------------------------------------------------------------
# Macro loader
# ---------------------------------------------------------------------------


def load_macro(data: dict[str, Any]) -> dict[str, Any]:
    """Single MacroSnapshot from the ``data_snapshot.dimensions`` structure."""
    snapshot = data.get("data_snapshot") or {}
    dimensions = snapshot.get("dimensions") or []

    indicator_index: dict[str, dict[str, Any]] = {}
    for dim in dimensions:
        for ind in dim.get("indicators") or []:
            label = (ind.get("indicator") or "").strip().lower()
            if label and label not in indicator_index:
                indicator_index[label] = ind

    def _pick(*keywords: str) -> dict[str, Any] | None:
        for label, ind in indicator_index.items():
            if all(kw in label for kw in keywords):
                return ind
        return None

    def _num(ind: dict[str, Any] | None) -> float | None:
        """Best-effort numeric extraction from a free-form macro value.

        Macro values are messy (``"Q1: 6.7%, Q2: 8.4%"``,
        ``"55.9 (Apr flash) / 53.9 (Mar final)"``, ``"3.40%"``). We try in
        order: number-followed-by-percent → number-with-decimal-point →
        first integer. The first match wins, so ``"Q1: 6.7%"`` resolves to
        ``6.7`` not ``1`` (the trailing digit of the ``"Q1"`` label).
        """
        if ind is None:
            return None
        v = ind.get("value")
        if v is None:
            return None
        s = str(v)
        # Prefer "<number>%" pattern (most macro indicators are percents).
        m = re.search(r"(-?\d+\.?\d*)\s*%", s)
        if m:
            return float(m.group(1))
        # Fall back: a number that has a decimal point + no immediately
        # preceding letter (skip "Q1", "FY26" etc.).
        m = re.search(r"(?<![A-Za-z])(-?\d+\.\d+)", s)
        if m:
            return float(m.group(1))
        # Last resort: any number.
        m = re.search(r"-?\d+\.?\d*", s)
        return float(m.group(0)) if m else None

    themes = [str(d.get("dimension")) for d in dimensions if d.get("dimension")]
    notes_lines: list[str] = []
    for dim in dimensions:
        notes_lines.append(f"# {dim.get('dimension', '')}")
        for ind in dim.get("indicators") or []:
            label = ind.get("indicator")
            value = ind.get("value")
            if label and value is not None:
                notes_lines.append(f"  {label}: {value}")

    return {
        "country_code": "IN",
        "snapshot_period": "2026-Q1",
        "snapshot_date": date_t(2026, 3, 31),
        "gdp_growth_pct": _num(_pick("gdp", "growth")),
        "cpi_inflation_pct": _num(_pick("cpi", "headline")),
        "wpi_inflation_pct": _num(_pick("wpi")),
        "repo_rate_pct": _num(_pick("repo")),
        "bond_yield_10y_pct": _num(
            _pick("10", "yield") or _pick("g-sec") or _pick("g_sec")
        ),
        "fx_usd_inr": _num(_pick("inr") or _pick("usd")),
        "themes": themes,
        "notes": "\n".join(notes_lines)[:5000],
    }


# ---------------------------------------------------------------------------
# Industry loader
# ---------------------------------------------------------------------------


def load_industry(key: str, data: dict[str, Any]) -> dict[str, Any]:
    """One IndustryReport per industry-data JSON file."""
    filename = data.get("filename") or key.split("/")[-1]
    base = filename.rsplit(".", 1)[0]
    industry_code = _slug(base)[:40]
    industry_name = base.replace("_", " ").strip()[:120] or industry_code
    pages = data.get("pages") or []
    summary_text = ""
    for p in pages:
        text = p.get("text") or ""
        if isinstance(text, str) and text.strip():
            summary_text = text.strip()[:1000]
            break
    return {
        "industry_code": industry_code,
        "industry_name": industry_name,
        "report_period": "2026-Q1",
        "report_date": date_t(2026, 3, 31),
        "outlook": "neutral",
        "summary": summary_text or industry_name,
        "key_themes": [],
        "drivers": [],
        "risks": [],
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def _synthetic_ticker(prefix: str, *parts: str) -> str:
    """Build a deterministic exchange_ticker for source-less instruments.

    Sources like PMS / Unlisted Equity have no ISIN / AMFI / ticker, so the
    upsert needs a synthetic identifier. A simple slug truncated to 32
    chars (the column width) collides easily for funds with long similar
    names. We slug + truncate + append an 8-char hash suffix to guarantee
    uniqueness while keeping the result mostly human-readable.
    """
    parts_filtered = [p for p in parts if p]
    full_slug = _slug("_".join((prefix, *parts_filtered)))
    if len(full_slug) <= 32:
        return full_slug
    head = full_slug[:23]
    tail = hashlib.sha256(full_slug.encode("utf-8")).hexdigest()[:8]
    return f"{head}_{tail}"


def _amc_from_name(name: str) -> str | None:
    """Crude heuristic: first word of a fund name is usually the AMC."""
    parts = name.strip().split()
    return parts[0] if parts else None


def _parse_loose_date(value: Any) -> date_t | None:
    """Best-effort date parse covering ISO + common display formats."""
    if not value or not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    # ISO / ISO-with-time
    try:
        return date_t.fromisoformat(s[:10])
    except ValueError:
        pass
    for fmt in ("%b %d, %Y", "%d %b %Y", "%B %d, %Y", "%d %B %Y"):
        try:
            return datetime_t.strptime(s, fmt).date()
        except ValueError:
            continue
    return None
