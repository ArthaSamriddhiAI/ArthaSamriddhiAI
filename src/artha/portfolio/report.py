"""Client review report — HTML generation for PDF export."""

from __future__ import annotations

from datetime import date
from typing import Any

from artha.portfolio.schemas import ASSET_CLASS_LABELS


REPORT_CSS = """
body { font-family: 'Segoe UI', Calibri, sans-serif; color: #1a202c; margin: 0; padding: 24px; font-size: 10pt; }
.header { display: flex; justify-content: space-between; align-items: center; border-bottom: 3px solid #C4962C; padding-bottom: 12px; margin-bottom: 16px; }
.header h1 { color: #0B2545; font-size: 18pt; margin: 0; }
.header .subtitle { color: #718096; font-size: 9pt; }
.header .date { color: #a0aec0; font-size: 8pt; }
.cards { display: flex; gap: 12px; margin-bottom: 16px; }
.card { flex: 1; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 10px; }
.card .label { font-size: 7pt; color: #718096; text-transform: uppercase; letter-spacing: 0.05em; }
.card .value { font-size: 14pt; font-weight: 700; margin-top: 2px; }
.card .value.positive { color: #16a34a; }
.card .value.negative { color: #dc2626; }
h2 { color: #134074; font-size: 12pt; margin: 16px 0 8px; border-bottom: 1px solid #e2e8f0; padding-bottom: 4px; }
h3 { color: #0B2545; font-size: 10pt; margin: 12px 0 6px; }
table { width: 100%; border-collapse: collapse; font-size: 8pt; margin: 8px 0; }
th { background: #0B2545; color: white; padding: 5px 6px; text-align: left; font-weight: 600; font-size: 7pt; }
td { padding: 4px 6px; border-bottom: 0.5px solid #e8e6de; }
tr:nth-child(even) { background: #fafaf7; }
.alloc-bar { display: flex; height: 20px; border-radius: 4px; overflow: hidden; margin: 8px 0; }
.alloc-segment { display: flex; align-items: center; justify-content: center; color: white; font-size: 7pt; font-weight: 600; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 7pt; font-weight: 600; }
.badge-green { background: #dcfce7; color: #166534; }
.badge-red { background: #fee2e2; color: #991b1b; }
.badge-blue { background: #dbeafe; color: #1e40af; }
.footer { margin-top: 24px; padding-top: 8px; border-top: 1px solid #e2e8f0; font-size: 7pt; color: #a0aec0; }
.disclaimer { font-size: 6.5pt; color: #a0aec0; margin-top: 12px; padding: 8px; background: #f8fafc; border-radius: 4px; }
@page { size: A4; margin: 15mm; }
"""

ALLOC_COLORS = {
    "equity": "#3b82f6", "mutual_fund": "#8b5cf6", "gold": "#f59e0b", "silver": "#94a3b8",
    "fd": "#22c55e", "bond": "#06b6d4", "pms": "#ec4899", "aif": "#f97316",
    "real_estate": "#84cc16", "insurance": "#6366f1", "crypto": "#eab308",
    "ppf": "#14b8a6", "nps": "#e11d48", "other": "#64748b",
}


def fmt_inr(v: float) -> str:
    if v is None:
        return "0"
    av = abs(v)
    if av >= 10_000_000:
        return f"{'Rs ' if v >= 0 else '-Rs '}{av / 10_000_000:,.2f} Cr"
    if av >= 100_000:
        return f"{'Rs ' if v >= 0 else '-Rs '}{av / 100_000:,.2f} L"
    return f"Rs {v:,.0f}"


def generate_report_html(
    summary: dict,
    performance: dict | None = None,
    drift: dict | None = None,
    risk_profile: dict | None = None,
    ai_commentary: str = "",
) -> str:
    """Generate a professional HTML report for PDF conversion."""
    name = summary.get("investor_name", "Client")
    today_str = date.today().strftime("%d %B %Y")
    invested = summary.get("total_invested", 0)
    current = summary.get("current_value", 0)
    gain = summary.get("total_gain_loss", 0)
    gain_pct = summary.get("total_gain_loss_pct", 0)
    holdings = summary.get("holdings", [])
    allocation = summary.get("allocation", [])

    # Header
    html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><style>{REPORT_CSS}</style></head><body>
    <div class="header">
      <div><h1>Portfolio Review Report</h1><div class="subtitle">{name}</div></div>
      <div style="text-align:right"><div class="date">Report Date: {today_str}</div>
      <div class="date">ArthaSamriddhiAI Portfolio Operating System</div></div>
    </div>"""

    # Summary cards
    gain_cls = "positive" if gain >= 0 else "negative"
    risk_cat = risk_profile.get("risk_category", "").replace("_", " ").title() if risk_profile else "N/A"
    html += f"""
    <div class="cards">
      <div class="card"><div class="label">Total Invested</div><div class="value">{fmt_inr(invested)}</div></div>
      <div class="card"><div class="label">Current Value</div><div class="value" style="color:#2563eb">{fmt_inr(current)}</div></div>
      <div class="card"><div class="label">Total Gain/Loss</div><div class="value {gain_cls}">{'+' if gain>=0 else ''}{fmt_inr(gain)} ({gain_pct:+.1f}%)</div></div>
      <div class="card"><div class="label">Holdings</div><div class="value">{summary.get('holdings_count',0)}</div></div>
      <div class="card"><div class="label">Risk Profile</div><div class="value">{risk_cat}</div></div>
    </div>"""

    # Allocation bar
    html += '<h2>Asset Allocation</h2><div class="alloc-bar">'
    for a in allocation:
        color = ALLOC_COLORS.get(a["asset_class"], "#94a3b8")
        label = f'{a["percentage"]:.0f}%' if a["percentage"] > 4 else ""
        html += f'<div class="alloc-segment" style="width:{a["percentage"]}%;background:{color}" title="{a["label"]}: {a["percentage"]:.1f}%">{label}</div>'
    html += "</div>"

    # Allocation table
    html += '<table><tr><th>Asset Class</th><th style="text-align:right">Current Value</th><th style="text-align:right">Allocation %</th><th style="text-align:right">Cost Basis</th><th style="text-align:right">Holdings</th></tr>'
    for a in allocation:
        html += f'<tr><td>{a["label"]}</td><td style="text-align:right">{fmt_inr(a["current_value"])}</td><td style="text-align:right">{a["percentage"]:.1f}%</td><td style="text-align:right">{fmt_inr(a["cost_value"])}</td><td style="text-align:right">{a["holdings_count"]}</td></tr>'
    html += "</table>"

    # Performance
    if performance:
        html += "<h2>Performance</h2>"
        pr = performance.get("period_returns", {})
        br = performance.get("benchmark_returns", {})
        al = performance.get("alpha", {})
        html += '<table><tr><th>Period</th><th style="text-align:right">Portfolio</th><th style="text-align:right">Nifty 50</th><th style="text-align:right">Alpha</th></tr>'
        for p in ["1M", "3M", "6M", "1Y", "3Y", "5Y"]:
            pv = f'{pr[p]:+.1f}%' if pr.get(p) is not None else "N/A"
            bv = f'{br[p]:+.1f}%' if br.get(p) is not None else "N/A"
            av = f'{al[p]:+.1f}%' if al.get(p) is not None else "N/A"
            html += f'<tr><td>{p}</td><td style="text-align:right">{pv}</td><td style="text-align:right">{bv}</td><td style="text-align:right">{av}</td></tr>'
        html += "</table>"

        # Top/Bottom
        top = performance.get("top_performers", [])
        bot = performance.get("bottom_performers", [])
        if top:
            html += '<h3>Top Performers</h3><table><tr><th>Holding</th><th style="text-align:right">Return %</th></tr>'
            for t in top[:5]:
                html += f'<tr><td>{t["description"]}</td><td style="text-align:right;color:#16a34a">{t["return_pct"]:+.1f}%</td></tr>'
            html += "</table>"
        if bot:
            html += '<h3>Bottom Performers</h3><table><tr><th>Holding</th><th style="text-align:right">Return %</th></tr>'
            for b in bot[:5]:
                html += f'<tr><td>{b["description"]}</td><td style="text-align:right;color:#dc2626">{b["return_pct"]:+.1f}%</td></tr>'
            html += "</table>"

    # Drift
    if drift and drift.get("drift_items"):
        html += "<h2>Rebalancing Analysis</h2>"
        needs = drift.get("needs_rebalance", False)
        html += f'<p>Maximum drift: {drift["max_drift_pct"]:.1f}% — {"<span style=\"color:#dc2626;font-weight:700\">Rebalancing recommended</span>" if needs else "<span style=\"color:#16a34a\">Within acceptable range</span>"}</p>'
        html += '<table><tr><th>Asset Class</th><th style="text-align:right">Target</th><th style="text-align:right">Actual</th><th style="text-align:right">Drift</th><th>Status</th></tr>'
        for d in drift["drift_items"][:10]:
            status_color = "#dc2626" if d["status"] != "on_target" else "#16a34a"
            html += f'<tr><td>{d["label"]}</td><td style="text-align:right">{d["target_pct"]:.1f}%</td><td style="text-align:right">{d["actual_pct"]:.1f}%</td><td style="text-align:right;color:{status_color}">{d["drift_pct"]:+.1f}%</td><td style="color:{status_color}">{d["status"].replace("_"," ").title()}</td></tr>'
        html += "</table>"

    # Holdings
    html += "<h2>Holdings Detail</h2>"
    html += '<table><tr><th>Type</th><th>Description</th><th style="text-align:right">Qty</th><th style="text-align:right">Cost</th><th style="text-align:right">Current</th><th style="text-align:right">Value</th><th style="text-align:right">Gain/Loss</th><th style="text-align:right">Return</th></tr>'
    for h in holdings:
        gl_color = "#16a34a" if (h.get("gain_loss", 0) or 0) >= 0 else "#dc2626"
        html += f'<tr><td><span class="badge badge-blue">{ASSET_CLASS_LABELS.get(h["asset_class"], h["asset_class"])}</span></td>'
        html += f'<td>{h["description"]}</td><td style="text-align:right">{h["quantity"]:,.0f}</td>'
        html += f'<td style="text-align:right">{fmt_inr(h.get("cost_value",0))}</td>'
        html += f'<td style="text-align:right">{h.get("current_price",""):,.2f}</td>'
        html += f'<td style="text-align:right">{fmt_inr(h.get("current_value",0))}</td>'
        html += f'<td style="text-align:right;color:{gl_color}">{fmt_inr(h.get("gain_loss",0))}</td>'
        html += f'<td style="text-align:right;color:{gl_color}">{h.get("gain_loss_pct",0):+.1f}%</td></tr>'
    html += "</table>"

    # AI Commentary
    if ai_commentary:
        html += f'<h2>AI Commentary</h2><div style="background:#eff6ff;border-left:3px solid #3b82f6;padding:10px;border-radius:0 4px 4px 0;font-size:8.5pt;line-height:1.6">{ai_commentary}</div>'

    # Disclaimer
    html += """
    <div class="disclaimer">
      <strong>Disclaimer:</strong> This report is generated by ArthaSamriddhiAI for informational purposes only. It does not constitute investment advice.
      Past performance is not indicative of future results. All investments are subject to market risk. Please consult your financial advisor before making investment decisions.
      The AI-generated commentary is advisory and does not represent a recommendation. Deterministic scoring and governance rules are the basis for all assessments.
    </div>
    <div class="footer">ArthaSamriddhiAI | Portfolio Operating System | Evidence-Governance-Accountability | Generated {today_str}</div>
    </body></html>"""

    return html
