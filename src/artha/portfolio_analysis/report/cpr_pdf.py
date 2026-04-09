"""CPR report — HTML generation and PDF export for the Comprehensive Portfolio Review."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


# ── Styles ───────────────────────────────────────────────────────────

CPR_CSS = """
body { font-family: 'Segoe UI', Calibri, sans-serif; color: #1a202c; margin: 0; padding: 24px; font-size: 10pt; }
.header { display: flex; justify-content: space-between; align-items: center; border-bottom: 3px solid #C4962C; padding-bottom: 12px; margin-bottom: 16px; }
.header h1 { color: #0B2545; font-size: 18pt; margin: 0; }
.header .subtitle { color: #718096; font-size: 9pt; }
.header .date { color: #a0aec0; font-size: 8pt; }
.cards { display: flex; gap: 12px; margin-bottom: 16px; }
.card { flex: 1; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 10px; }
.card .label { font-size: 7pt; color: #718096; text-transform: uppercase; letter-spacing: 0.05em; }
.card .value { font-size: 14pt; font-weight: 700; margin-top: 2px; }
.card .value.high { color: #dc2626; }
.card .value.medium { color: #f59e0b; }
.card .value.low { color: #16a34a; }
h2 { color: #134074; font-size: 12pt; margin: 16px 0 8px; border-bottom: 1px solid #e2e8f0; padding-bottom: 4px; }
h3 { color: #0B2545; font-size: 10pt; margin: 12px 0 6px; }
table { width: 100%; border-collapse: collapse; font-size: 8pt; margin: 8px 0; }
th { background: #0B2545; color: white; padding: 5px 6px; text-align: left; font-weight: 600; font-size: 7pt; }
td { padding: 4px 6px; border-bottom: 0.5px solid #e8e6de; }
tr:nth-child(even) { background: #fafaf7; }
.risk-badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 7pt; font-weight: 600; }
.risk-low { background: #dcfce7; color: #166534; }
.risk-medium { background: #fef9c3; color: #854d0e; }
.risk-high { background: #fee2e2; color: #991b1b; }
.risk-critical { background: #991b1b; color: #ffffff; }
.alloc-bar { display: flex; height: 20px; border-radius: 4px; overflow: hidden; margin: 8px 0; }
.alloc-segment { display: flex; align-items: center; justify-content: center; color: white; font-size: 7pt; font-weight: 600; }
.section-note { background: #eff6ff; border-left: 3px solid #3b82f6; padding: 10px; border-radius: 0 4px 4px 0; font-size: 8.5pt; line-height: 1.6; margin: 8px 0; }
.driver-list { list-style: none; padding: 0; margin: 4px 0; }
.driver-list li { padding: 2px 0; font-size: 8.5pt; }
.driver-list li::before { content: "\\25B8 "; color: #3b82f6; }
.flag-item { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 7pt; font-weight: 600; background: #fef3c7; color: #92400e; margin: 2px; }
.footer { margin-top: 24px; padding-top: 8px; border-top: 1px solid #e2e8f0; font-size: 7pt; color: #a0aec0; }
.disclaimer { font-size: 6.5pt; color: #a0aec0; margin-top: 12px; padding: 8px; background: #f8fafc; border-radius: 4px; }
@page { size: A4; margin: 15mm; }
"""

ALLOC_COLORS = {
    "listed_equity": "#3b82f6",
    "mutual_fund": "#8b5cf6",
    "pms": "#ec4899",
    "aif_cat1": "#f97316",
    "aif_cat2": "#f59e0b",
    "aif_cat3": "#eab308",
    "unlisted_equity": "#84cc16",
    "cash": "#94a3b8",
}

ASSET_CLASS_LABELS = {
    "listed_equity": "Listed Equity",
    "mutual_fund": "Mutual Fund",
    "pms": "PMS",
    "aif_cat1": "AIF Cat I",
    "aif_cat2": "AIF Cat II",
    "aif_cat3": "AIF Cat III",
    "unlisted_equity": "Unlisted Equity",
    "cash": "Cash",
}


def _fmt_inr(v: float | None) -> str:
    if v is None:
        return "0"
    av = abs(v)
    sign = "" if v >= 0 else "-"
    if av >= 10_000_000:
        return f"{sign}Rs {av / 10_000_000:,.2f} Cr"
    if av >= 100_000:
        return f"{sign}Rs {av / 100_000:,.2f} L"
    return f"Rs {v:,.0f}"


def _risk_badge(level: str) -> str:
    css_class = f"risk-{level}" if level in ("low", "medium", "high", "critical") else "risk-medium"
    return f'<span class="risk-badge {css_class}">{level.upper()}</span>'


# ── HTML Generation ──────────────────────────────────────────────────

def generate_cpr_html(cpr: dict, client_name: str, review_date: str) -> str:
    """Generate complete HTML for all 10 CPR sections.

    Parameters
    ----------
    cpr : dict
        The CPR dict returned by ``PortfolioAnalysisOrchestrator.run_phase1_cpr``.
    client_name : str
        Display name of the client.
    review_date : str
        Date string for the report header.

    Returns
    -------
    str — full HTML document.
    """
    sections = cpr.get("sections", {})

    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><style>{CPR_CSS}</style></head><body>
<div class="header">
  <div>
    <h1>Comprehensive Portfolio Review</h1>
    <div class="subtitle">{_esc(client_name)}</div>
  </div>
  <div style="text-align:right">
    <div class="date">Report Date: {_esc(review_date)}</div>
    <div class="date">Review ID: {_esc(cpr.get("review_id", ""))}</div>
    <div class="date">Samriddhi AI Portfolio Operating System</div>
  </div>
</div>"""

    # S1: Executive Summary
    es = sections.get("executive_summary", {})
    risk_cls = es.get("overall_risk_level", "medium")
    html += f"""
<div class="cards">
  <div class="card"><div class="label">Total AUM</div><div class="value">{_fmt_inr(es.get("total_aum", 0))}</div></div>
  <div class="card"><div class="label">Holdings</div><div class="value">{es.get("holdings_count", 0)}</div></div>
  <div class="card"><div class="label">Overall Risk</div><div class="value {risk_cls}">{risk_cls.upper()}</div></div>
  <div class="card"><div class="label">Confidence</div><div class="value">{es.get("overall_confidence", 0):.0%}</div></div>
</div>"""

    if es.get("synthesis_summary"):
        html += f'<div class="section-note">{_esc(es["synthesis_summary"])}</div>'

    if es.get("key_drivers"):
        html += '<h3>Key Drivers</h3><ul class="driver-list">'
        for d in es["key_drivers"]:
            html += f"<li>{_esc(d)}</li>"
        html += "</ul>"

    # S2: Asset Allocation
    html += "<h2>Asset Allocation</h2>"
    alloc = sections.get("asset_allocation", {})
    breakdown = alloc.get("breakdown", [])
    if breakdown:
        html += '<div class="alloc-bar">'
        for ab in breakdown:
            ac = ab.get("asset_class", "cash")
            color = ALLOC_COLORS.get(ac, "#94a3b8")
            pct = ab.get("weight_pct", 0)
            label_text = f'{pct:.0f}%' if pct > 4 else ""
            html += f'<div class="alloc-segment" style="width:{pct}%;background:{color}" title="{ASSET_CLASS_LABELS.get(ac, ac)}: {pct:.1f}%">{label_text}</div>'
        html += "</div>"

        html += '<table><tr><th>Asset Class</th><th style="text-align:right">Value</th><th style="text-align:right">Weight %</th><th style="text-align:right">Holdings</th></tr>'
        for ab in breakdown:
            ac = ab.get("asset_class", "")
            html += f'<tr><td>{ASSET_CLASS_LABELS.get(ac, ac)}</td><td style="text-align:right">{_fmt_inr(ab.get("total_value_inr", 0))}</td><td style="text-align:right">{ab.get("weight_pct", 0):.1f}%</td><td style="text-align:right">{ab.get("holdings_count", 0)}</td></tr>'
        html += "</table>"

    conc_flags = alloc.get("concentration_flags", [])
    if conc_flags:
        html += "<h3>Concentration Flags</h3>"
        for f in conc_flags:
            html += f'<span class="flag-item">{_esc(f)}</span> '

    # S3: Risk Assessment
    html += "<h2>Risk Assessment Summary</h2>"
    ra = sections.get("risk_assessment", {})
    risk_dist = ra.get("risk_distribution", {})
    if risk_dist:
        html += '<table><tr><th>Risk Level</th><th style="text-align:right">Holdings Count</th></tr>'
        for level in ("low", "medium", "high", "critical"):
            count = risk_dist.get(level, 0)
            if count > 0:
                html += f"<tr><td>{_risk_badge(level)}</td><td style='text-align:right'>{count}</td></tr>"
        html += "</table>"

    high_risk = ra.get("high_risk_holdings", [])
    if high_risk:
        html += "<h3>High/Critical Risk Holdings</h3>"
        html += '<table><tr><th>Holding</th><th>Asset Class</th><th>Risk</th><th>Top Drivers</th></tr>'
        for hr in high_risk:
            drivers_str = "; ".join(hr.get("top_drivers", []))
            html += f'<tr><td>{_esc(hr.get("instrument_name", ""))}</td><td>{ASSET_CLASS_LABELS.get(hr.get("asset_class", ""), hr.get("asset_class", ""))}</td><td>{_risk_badge(hr.get("risk_level", "high"))}</td><td>{_esc(drivers_str)}</td></tr>'
        html += "</table>"

    # S4: Individual Holding Analysis
    html += "<h2>Individual Holding Analysis</h2>"
    ha = sections.get("holding_analysis", {})
    assessments = ha.get("holding_assessments", [])
    if assessments:
        html += '<table><tr><th>ID</th><th>Instrument</th><th>Asset Class</th><th>Risk</th><th>Top Drivers</th><th>Flags</th></tr>'
        for a in assessments:
            drivers_str = "; ".join(a.get("top_drivers", []))
            flags_str = " ".join(
                f'<span class="flag-item">{_esc(f)}</span>' for f in a.get("flags", [])
            )
            html += f'<tr><td>{_esc(a.get("holding_id", ""))}</td><td>{_esc(a.get("instrument_name", ""))}</td><td>{ASSET_CLASS_LABELS.get(a.get("asset_class", ""), a.get("asset_class", ""))}</td><td>{_risk_badge(a.get("risk_level", "medium"))}</td><td>{_esc(drivers_str)}</td><td>{flags_str}</td></tr>'
        html += "</table>"

    # S5-S7: Cross-portfolio agent sections
    for section_key, section_title in [
        ("industry_business", "Industry & Business Environment"),
        ("macro_environment", "Macro Environment"),
        ("behavioural_historical", "Behavioural & Historical Patterns"),
    ]:
        html += f"<h2>{section_title}</h2>"
        sec = sections.get(section_key, {})
        if sec.get("status") == "not_available":
            html += '<div class="section-note">Analysis not available for this section.</div>'
        else:
            if sec.get("summary"):
                html += f'<div class="section-note">{_esc(sec["summary"])}</div>'
            if sec.get("drivers"):
                html += '<ul class="driver-list">'
                for d in sec["drivers"]:
                    html += f"<li>{_esc(d)}</li>"
                html += "</ul>"
            if sec.get("flags"):
                for f in sec["flags"]:
                    html += f'<span class="flag-item">{_esc(f)}</span> '

    # S8: Data Quality
    html += "<h2>Data Quality & Gaps</h2>"
    dq = sections.get("data_quality", {})
    html += f"""
<table>
<tr><td>Total Holdings</td><td style="text-align:right">{dq.get("total_holdings", 0)}</td></tr>
<tr><td>Holdings with Gaps</td><td style="text-align:right">{dq.get("holdings_with_gaps", 0)}</td></tr>
<tr><td>Total Data Gaps</td><td style="text-align:right">{dq.get("total_data_gaps", 0)}</td></tr>
</table>"""
    if dq.get("note"):
        html += f'<div class="section-note">{_esc(dq["note"])}</div>'

    # S9: Conflicts
    html += "<h2>Conflicts & Divergences</h2>"
    conflicts = sections.get("conflicts", {})
    agent_conflicts = conflicts.get("agent_conflicts", [])
    if agent_conflicts:
        html += '<ul class="driver-list">'
        for c in agent_conflicts:
            html += f"<li>{_esc(c)}</li>"
        html += "</ul>"
    else:
        html += '<div class="section-note">No inter-agent conflicts detected.</div>'

    cflags = conflicts.get("flags", [])
    if cflags:
        for f in cflags:
            html += f'<span class="flag-item">{_esc(f)}</span> '

    # S10: Recommended Actions
    html += "<h2>Recommended Actions</h2>"
    rec = sections.get("recommended_actions", {})
    actions = rec.get("actions", [])
    if actions:
        html += '<table><tr><th>Symbol</th><th>Action</th><th style="text-align:right">Target Weight</th><th>Rationale</th></tr>'
        for a in actions:
            tw = a.get("target_weight")
            tw_str = f"{tw:.1f}%" if tw is not None else "N/A"
            html += f'<tr><td>{_esc(a.get("symbol", ""))}</td><td>{_esc(a.get("action", ""))}</td><td style="text-align:right">{tw_str}</td><td>{_esc(a.get("rationale", ""))}</td></tr>'
        html += "</table>"
    else:
        html += '<div class="section-note">No specific actions recommended at this time.</div>'

    # Disclaimer & Footer
    html += """
<div class="disclaimer">
  <strong>Disclaimer:</strong> This Comprehensive Portfolio Review is generated by Samriddhi AI for informational purposes only.
  It does not constitute investment advice, a recommendation, or an offer to buy or sell any security.
  Past performance is not indicative of future results. All investments are subject to market risk.
  Please consult your financial advisor before making investment decisions.
  AI-generated analysis is advisory only. Deterministic scoring and governance rules are the basis for all risk assessments.
  Tax calculations are estimates based on prevailing rates and should be verified with a qualified tax professional.
</div>
<div class="footer">
  Samriddhi AI | Portfolio Operating System | Evidence-Governance-Accountability | Comprehensive Portfolio Review
</div>
</body></html>"""

    return html


def _esc(val: Any) -> str:
    """HTML-escape a value."""
    if val is None:
        return ""
    s = str(val)
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


# ── PDF Generation ───────────────────────────────────────────────────

async def generate_cpr_pdf(review_id: str, session: AsyncSession) -> bytes:
    """Load CPR from telemetry, generate HTML, convert to PDF via Playwright.

    Parameters
    ----------
    review_id : str
        The portfolio review ID.
    session : AsyncSession
        Active DB session to load the telemetry record.

    Returns
    -------
    bytes — the generated PDF content.
    """
    from sqlalchemy import select

    from artha.accountability.models import TraceNodeRow

    # Load the portfolio_review_complete trace node
    stmt = select(TraceNodeRow).where(
        TraceNodeRow.decision_id == review_id,
        TraceNodeRow.node_type == "portfolio_review_complete",
    )
    result = await session.execute(stmt)
    row = result.scalars().first()

    if row is None:
        raise ValueError(f"No portfolio_review_complete event found for review_id={review_id}")

    event_data = json.loads(row.data_json) if isinstance(row.data_json, str) else row.data_json
    cpr = event_data.get("cpr_sections", {})

    # Extract client name and date
    exec_summary = cpr.get("sections", {}).get("executive_summary", {})
    client_name = exec_summary.get("client_name", "Client")
    review_date = exec_summary.get("review_date", date.today().strftime("%d %B %Y"))

    # Generate HTML
    html = generate_cpr_html(cpr, client_name, review_date)

    # Convert to PDF via Playwright (same pattern as existing report.py)
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(html, wait_until="networkidle")
        pdf_bytes = await page.pdf(
            format="A4",
            margin={"top": "15mm", "right": "15mm", "bottom": "15mm", "left": "15mm"},
            print_background=True,
        )
        await browser.close()

    return pdf_bytes
