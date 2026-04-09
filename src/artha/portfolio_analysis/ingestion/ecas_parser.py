"""Parse CAMS/KFintech ECAS files (XML format) into the canonical portfolio JSON."""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET
from datetime import date
from typing import Any


def _safe_float(val: str | None) -> float | None:
    if val is None:
        return None
    try:
        return float(val.strip().replace(",", ""))
    except (ValueError, TypeError):
        return None


def _safe_text(elem: ET.Element | None, tag: str) -> str | None:
    """Extract text from a child element, returning None if absent."""
    if elem is None:
        return None
    child = elem.find(tag)
    if child is None or child.text is None:
        return None
    return child.text.strip()


def parse_ecas(file_bytes: bytes, file_type: str = "xml") -> dict:
    """Parse a CAMS/KFintech ECAS file into canonical portfolio JSON.

    Parameters
    ----------
    file_bytes : bytes
        Raw file content.
    file_type : str
        Currently only ``"xml"`` is supported.

    Returns
    -------
    dict with keys: holdings, asset_class_breakdown, data_quality_summary, total_value_inr
    """
    if file_type != "xml":
        raise ValueError(f"Unsupported ECAS file type: {file_type}. Only 'xml' is supported.")

    tree = ET.parse(io.BytesIO(file_bytes))
    root = tree.getroot()

    # Namespace-agnostic element search
    def _find_all(tag: str) -> list[ET.Element]:
        """Find elements matching tag, ignoring XML namespace prefixes."""
        found = root.findall(f".//{tag}")
        if not found:
            # Try with common namespace patterns
            for elem in root.iter():
                local = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                if local.lower() == tag.lower():
                    found.append(elem)
        return found

    # Look for folio/fund elements — ECAS files vary in structure
    # Common tags: Folio, FolioDetail, Fund, Scheme, MutualFund, Transaction
    folio_elems = (
        _find_all("Folio")
        or _find_all("FolioDetail")
        or _find_all("Fund")
        or _find_all("Scheme")
    )

    # If no recognised folio-level elements, try to treat each second-level element as a holding
    if not folio_elems:
        folio_elems = list(root)

    holdings: list[dict] = []
    data_gaps: list[dict] = []
    total_value = 0.0
    today = date.today()
    row_num = 0

    for elem in folio_elems:
        row_num += 1
        holding_id = f"h-{row_num:03d}"

        # Extract fields — try multiple common tag names
        scheme_name = (
            _safe_text(elem, "SchemeName")
            or _safe_text(elem, "scheme_name")
            or _safe_text(elem, "FundName")
            or _safe_text(elem, "Name")
            or _safe_text(elem, "Description")
        )
        if not scheme_name:
            # Use element text or tag as fallback
            scheme_name = elem.text.strip() if elem.text and elem.text.strip() else None

        if not scheme_name:
            continue  # skip elements that don't look like holdings

        amfi_code = (
            _safe_text(elem, "AMFICode")
            or _safe_text(elem, "amfi_code")
            or _safe_text(elem, "SchemeCode")
            or _safe_text(elem, "FundCode")
        )

        current_units = _safe_float(
            _safe_text(elem, "ClosingUnits")
            or _safe_text(elem, "CurrentUnits")
            or _safe_text(elem, "Units")
            or _safe_text(elem, "closing_units")
        )

        current_nav = _safe_float(
            _safe_text(elem, "NAV")
            or _safe_text(elem, "CurrentNAV")
            or _safe_text(elem, "nav")
        )

        current_value = _safe_float(
            _safe_text(elem, "CurrentValue")
            or _safe_text(elem, "MarketValue")
            or _safe_text(elem, "Value")
            or _safe_text(elem, "current_value")
        )

        folio_number = (
            _safe_text(elem, "FolioNo")
            or _safe_text(elem, "FolioNumber")
            or _safe_text(elem, "folio_no")
            or elem.get("FolioNo")
            or elem.get("folio_no")
        )

        # Derive value from units * NAV if not directly available
        if current_value is None and current_units is not None and current_nav is not None:
            current_value = current_units * current_nav

        gaps_for_holding: list[str] = []

        if current_value is None:
            gaps_for_holding.append("current_value")
            current_value = 0.0
        if current_units is None:
            gaps_for_holding.append("current_units")
        if current_nav is None:
            gaps_for_holding.append("current_nav")

        # Cost basis is NOT available in ECAS — always flagged as data gap
        gaps_for_holding.append("cost_basis")

        total_value += current_value

        if gaps_for_holding:
            data_gaps.append({
                "holding_id": holding_id,
                "field": ", ".join(gaps_for_holding),
                "issue": "missing_data" if "cost_basis" not in gaps_for_holding or len(gaps_for_holding) > 1 else "ecas_no_cost_basis",
            })

        holding = {
            "holding_id": holding_id,
            "instrument_name": scheme_name,
            "isin_or_cin": amfi_code,
            "asset_class": "mutual_fund",
            "current_value_inr": current_value,
            "purchase_date": None,
            "purchase_price_per_unit": None,
            "quantity_or_units": current_units,
            "folio_or_account_no": folio_number,
            "cost_basis": None,  # Not available in ECAS
            "weight_pct": 0.0,
            "holding_period_days": None,
            "ltcg_eligible": None,
            "data_gaps": gaps_for_holding,
            # ECAS-specific fields
            "amfi_code": amfi_code,
            "current_nav": current_nav,
            "current_units": current_units,
        }
        holdings.append(holding)

    # Compute weight_pct
    if total_value > 0:
        for h in holdings:
            h["weight_pct"] = round((h["current_value_inr"] / total_value) * 100, 4)

    # Asset class breakdown (all mutual_fund for ECAS)
    asset_class_breakdown = []
    if holdings:
        asset_class_breakdown.append({
            "asset_class": "mutual_fund",
            "total_value_inr": total_value,
            "weight_pct": 100.0,
            "holdings_count": len(holdings),
        })

    data_quality_summary = {
        "total_holdings": len(holdings),
        "holdings_with_gaps": len({g["holding_id"] for g in data_gaps}),
        "total_data_gaps": len(data_gaps),
        "gap_details": data_gaps,
        "source": "ecas",
        "note": "Cost basis is not available in ECAS files. Advise client to provide purchase records.",
    }

    return {
        "holdings": holdings,
        "asset_class_breakdown": asset_class_breakdown,
        "data_quality_summary": data_quality_summary,
        "total_value_inr": total_value,
    }
