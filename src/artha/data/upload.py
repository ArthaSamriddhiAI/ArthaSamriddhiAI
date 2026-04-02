"""CSV upload endpoint for Bloomberg-sourced and manual data."""

from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import String, Date, Float, Text, DateTime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from artha.common.db.base import Base
from artha.common.db.session import get_session

router = APIRouter(prefix="/data", tags=["data"])


class DataUploadRow(Base):
    """Audit log of all CSV uploads."""
    __tablename__ = "data_uploads"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    data_type: Mapped[str] = mapped_column(String(64), nullable=False)
    filename: Mapped[str] = mapped_column(String(256), nullable=False)
    records_count: Mapped[int] = mapped_column(default=0)
    uploaded_by: Mapped[str] = mapped_column(String(128), default="system")
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="completed")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class GenericDataRow(Base):
    """Generic key-value data store for uploaded CSV data."""
    __tablename__ = "uploaded_data"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    data_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    upload_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    row_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# Expected columns per data type (for validation)
EXPECTED_SCHEMAS = {
    "stock_fundamentals": ["symbol", "px_last", "pe_ratio", "pb_ratio", "roe", "eps", "target_price", "market_cap", "sector"],
    "mf_risk_metrics": ["scheme_name", "nav", "aum", "sharpe_ratio", "sortino_ratio", "max_drawdown", "expense_ratio"],
    "yield_curve": ["tenor", "yield_pct", "date"],
    "corporate_bonds": ["isin", "issuer", "coupon", "ytm", "rating", "maturity", "issue_size"],
    "esg_scores": ["symbol", "env_score", "social_score", "gov_score", "esg_combined"],
    "analyst_consensus": ["symbol", "target_price", "consensus_rating", "buy_count", "hold_count", "sell_count", "eps_estimate"],
    "ownership_data": ["symbol", "promoter_pct", "fii_pct", "dii_pct", "mf_pct"],
    "pms_data": ["pms_name", "manager", "strategy", "aum_cr", "return_1yr"],
    "aif_data": ["aif_name", "category", "manager", "irr", "tvpi"],
    "fd_rates": ["bank", "tenor_months", "rate_pct", "senior_citizen_rate"],
    "cds_spreads": ["entity", "tenor", "spread_bps", "date"],
    "generic": [],  # Accept anything
}


@router.post("/upload")
async def upload_csv(
    data_type: str,
    uploaded_by: str = "system",
    notes: str | None = None,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
):
    """Upload a CSV file. Data type determines validation schema."""
    if data_type not in EXPECTED_SCHEMAS:
        raise HTTPException(400, f"Unknown data_type: {data_type}. Valid types: {list(EXPECTED_SCHEMAS.keys())}")

    content = await file.read()
    text = content.decode("utf-8-sig")  # Handle BOM
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)

    if not rows:
        raise HTTPException(400, "CSV file is empty")

    # Validate columns
    expected = EXPECTED_SCHEMAS[data_type]
    if expected:
        actual_cols = {c.lower().strip() for c in rows[0].keys()}
        missing = set(expected) - actual_cols
        if missing:
            raise HTTPException(400, f"Missing required columns: {missing}. Expected: {expected}. Got: {list(rows[0].keys())}")

    # Store
    upload_id = str(uuid.uuid4())
    now = datetime.now(UTC)

    session.add(DataUploadRow(
        id=upload_id, data_type=data_type, filename=file.filename or "upload.csv",
        records_count=len(rows), uploaded_by=uploaded_by, uploaded_at=now, notes=notes,
    ))

    for row in rows:
        clean = {k.lower().strip(): v.strip() if isinstance(v, str) else v for k, v in row.items()}
        session.add(GenericDataRow(
            id=str(uuid.uuid4()), data_type=data_type, upload_id=upload_id,
            row_json=json.dumps(clean, default=str), created_at=now,
        ))

    await session.commit()
    return {
        "upload_id": upload_id,
        "data_type": data_type,
        "records": len(rows),
        "filename": file.filename,
        "status": "completed",
    }


@router.get("/uploads")
async def list_uploads(
    data_type: str | None = None,
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
):
    """List recent data uploads."""
    from sqlalchemy import select
    stmt = select(DataUploadRow).order_by(DataUploadRow.uploaded_at.desc()).limit(limit)
    if data_type:
        stmt = stmt.where(DataUploadRow.data_type == data_type)
    result = await session.execute(stmt)
    return [
        {"id": r.id, "data_type": r.data_type, "filename": r.filename, "records": r.records_count,
         "uploaded_by": r.uploaded_by, "uploaded_at": r.uploaded_at.isoformat(), "notes": r.notes}
        for r in result.scalars()
    ]


@router.get("/uploads/{upload_id}/data")
async def get_upload_data(upload_id: str, limit: int = 500, session: AsyncSession = Depends(get_session)):
    """Get the actual data rows from an upload."""
    from sqlalchemy import select
    stmt = select(GenericDataRow).where(GenericDataRow.upload_id == upload_id).limit(limit)
    result = await session.execute(stmt)
    return [json.loads(r.row_json) for r in result.scalars()]


@router.get("/schemas")
async def get_schemas():
    """Get expected column schemas for each data type."""
    return EXPECTED_SCHEMAS
