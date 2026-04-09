"""Portfolio service — CRUD + valuation + lifecycle (DRAFT/LIVE)."""

from __future__ import annotations

import csv
import io
import json
import logging
import uuid
from datetime import UTC, datetime
from collections import defaultdict

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from artha.portfolio.models import (
    PortfolioEditLogRow,
    PortfolioHoldingRow,
    PortfolioSnapshotRow,
    PortfolioStateRow,
)
from artha.portfolio.schemas import (
    ASSET_CLASS_LABELS,
    AddHoldingRequest,
    AllocationItem,
    EditLogEntry,
    FreezeRequest,
    HoldingResponse,
    PortfolioStatusResponse,
    PortfolioSummary,
    UnfreezeRequest,
    UpdateHoldingRequest,
)

logger = logging.getLogger(__name__)


class PortfolioService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Lifecycle ──

    async def get_or_create_state(self, investor_id: str) -> PortfolioStateRow:
        """Get portfolio state, creating DRAFT if none exists."""
        stmt = select(PortfolioStateRow).where(PortfolioStateRow.investor_id == investor_id)
        result = await self._session.execute(stmt)
        state = result.scalar_one_or_none()
        if state is None:
            now = datetime.now(UTC)
            state = PortfolioStateRow(
                id=str(uuid.uuid4()),
                investor_id=investor_id,
                status="draft",
                version=1,
                created_at=now,
                updated_at=now,
            )
            self._session.add(state)
            await self._session.flush()
        return state

    async def get_status(self, investor_id: str) -> PortfolioStatusResponse:
        state = await self.get_or_create_state(investor_id)
        return PortfolioStatusResponse(
            investor_id=investor_id,
            status=state.status,
            version=state.version,
            onboarding_type=state.onboarding_type,
            frozen_at=state.frozen_at.isoformat() if state.frozen_at else None,
            frozen_by=state.frozen_by,
            is_editable=state.status == "draft",
        )

    async def set_onboarding_type(self, investor_id: str, onboarding_type: str) -> PortfolioStatusResponse:
        state = await self.get_or_create_state(investor_id)
        state.onboarding_type = onboarding_type
        state.updated_at = datetime.now(UTC)
        await self._session.flush()
        await self._log_edit(investor_id, None, "set_onboarding_type", "onboarding_type", None, onboarding_type)
        return await self.get_status(investor_id)

    async def freeze_portfolio(self, investor_id: str, req: FreezeRequest) -> PortfolioStatusResponse:
        """Transition portfolio from DRAFT to LIVE. Creates immutable snapshot."""
        state = await self.get_or_create_state(investor_id)
        if state.status == "live":
            raise ValueError("Portfolio is already LIVE. Unfreeze first to make changes.")

        now = datetime.now(UTC)

        # Build snapshot of current holdings
        summary = await self.get_portfolio_summary(investor_id)
        holdings_data = [h.model_dump(mode="json") for h in summary.holdings]

        snapshot = PortfolioSnapshotRow(
            id=str(uuid.uuid4()),
            investor_id=investor_id,
            version=state.version,
            holdings_json=json.dumps(holdings_data, default=str),
            total_invested=summary.total_invested,
            current_value=summary.current_value,
            frozen_at=now,
            frozen_by=req.frozen_by,
        )
        self._session.add(snapshot)

        # Update state
        state.status = "live"
        state.frozen_at = now
        state.frozen_by = req.frozen_by
        state.updated_at = now
        await self._session.flush()

        await self._log_edit(
            investor_id, None, "freeze", None, "draft", "live",
            actor=req.frozen_by,
            detail=f"Portfolio frozen at version {state.version} with {summary.holdings_count} holdings",
        )
        return await self.get_status(investor_id)

    async def unfreeze_portfolio(self, investor_id: str, req: UnfreezeRequest) -> PortfolioStatusResponse:
        """Transition portfolio from LIVE to DRAFT. Preserves LIVE snapshot in history."""
        state = await self.get_or_create_state(investor_id)
        if state.status == "draft":
            raise ValueError("Portfolio is already in DRAFT state.")

        now = datetime.now(UTC)
        state.status = "draft"
        state.version += 1
        state.unfrozen_at = now
        state.unfrozen_by = req.unfrozen_by
        state.frozen_at = None
        state.frozen_by = None
        state.updated_at = now
        await self._session.flush()

        await self._log_edit(
            investor_id, None, "unfreeze", None, "live", "draft",
            actor=req.unfrozen_by,
            detail=f"Portfolio unfrozen to version {state.version}. Reason: {req.reason}",
        )
        return await self.get_status(investor_id)

    async def _check_editable(self, investor_id: str) -> None:
        """Raise if portfolio is LIVE (not editable)."""
        state = await self.get_or_create_state(investor_id)
        if state.status == "live":
            raise ValueError("Portfolio is LIVE and immutable. Unfreeze to make changes.")

    async def _log_edit(
        self, investor_id: str, holding_id: str | None, action: str,
        field_changed: str | None = None, old_value: str | None = None,
        new_value: str | None = None, actor: str = "advisor", detail: str | None = None,
    ) -> None:
        """Log a portfolio edit for audit trail."""
        log = PortfolioEditLogRow(
            id=str(uuid.uuid4()),
            investor_id=investor_id,
            holding_id=holding_id,
            action=action,
            field_changed=field_changed,
            old_value=str(old_value) if old_value is not None else None,
            new_value=str(new_value) if new_value is not None else None,
            actor=actor,
            detail=detail,
            created_at=datetime.now(UTC),
        )
        self._session.add(log)

    async def get_edit_log(self, investor_id: str, limit: int = 50) -> list[EditLogEntry]:
        """Get portfolio edit history for audit trail."""
        stmt = (
            select(PortfolioEditLogRow)
            .where(PortfolioEditLogRow.investor_id == investor_id)
            .order_by(PortfolioEditLogRow.created_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        rows = result.scalars().all()
        return [
            EditLogEntry(
                id=r.id, action=r.action, holding_id=r.holding_id,
                field_changed=r.field_changed, old_value=r.old_value,
                new_value=r.new_value, actor=r.actor, detail=r.detail,
                created_at=r.created_at.isoformat() if r.created_at else "",
            )
            for r in rows
        ]

    # ── CRUD (with DRAFT guard) ──

    async def add_holding(self, investor_id: str, req: AddHoldingRequest) -> HoldingResponse:
        await self._check_editable(investor_id)
        now = datetime.now(UTC)
        row = PortfolioHoldingRow(
            id=str(uuid.uuid4()),
            investor_id=investor_id,
            asset_class=req.asset_class,
            symbol_or_id=req.symbol_or_id,
            description=req.description,
            quantity=req.quantity,
            acquisition_date=req.acquisition_date,
            acquisition_price=req.acquisition_price,
            current_price=req.current_price,
            notes=req.notes,
            active=True,
            created_at=now,
            updated_at=now,
        )
        self._session.add(row)
        await self._session.flush()
        await self._log_edit(
            investor_id, row.id, "add", None, None,
            f"{req.asset_class}: {req.symbol_or_id} ({req.description})",
            detail=f"Added {req.quantity} units at Rs {req.acquisition_price}",
        )
        return self._to_response(row)

    async def update_holding(self, investor_id: str, holding_id: str, req: UpdateHoldingRequest) -> HoldingResponse:
        """Update fields on an existing holding (DRAFT only)."""
        await self._check_editable(investor_id)
        stmt = select(PortfolioHoldingRow).where(
            PortfolioHoldingRow.id == holding_id,
            PortfolioHoldingRow.investor_id == investor_id,
            PortfolioHoldingRow.active == True,
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            raise ValueError("Holding not found")

        now = datetime.now(UTC)
        update_data = req.model_dump(exclude_none=True)
        for field, new_val in update_data.items():
            old_val = getattr(row, field, None)
            if old_val != new_val:
                await self._log_edit(
                    investor_id, holding_id, "edit", field,
                    str(old_val), str(new_val),
                )
                setattr(row, field, new_val)
        row.updated_at = now
        await self._session.flush()
        return self._to_response(row)

    async def delete_holding(self, holding_id: str, investor_id: str | None = None) -> bool:
        stmt = select(PortfolioHoldingRow).where(PortfolioHoldingRow.id == holding_id)
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            return False
        # Check editable
        if investor_id:
            await self._check_editable(investor_id)
        else:
            await self._check_editable(row.investor_id)
        row.active = False
        row.updated_at = datetime.now(UTC)
        await self._session.flush()
        await self._log_edit(
            row.investor_id, holding_id, "delete", None, None,
            f"{row.asset_class}: {row.symbol_or_id} ({row.description})",
            detail=f"Deleted holding of {row.quantity} units",
        )
        return True

    async def import_csv(self, investor_id: str, csv_text: str) -> dict:
        await self._check_editable(investor_id)
        reader = csv.DictReader(io.StringIO(csv_text))
        now = datetime.now(UTC)
        added = 0
        errors = []

        for i, row in enumerate(reader):
            try:
                asset_class = row.get("asset_class", "").strip().lower()
                symbol = row.get("symbol_or_id", "").strip()
                desc = row.get("description", "").strip()
                qty = float(row.get("quantity", 0))
                acq_date = row.get("acquisition_date", "").strip()
                acq_price = float(row.get("acquisition_price", 0))
                notes = row.get("notes", "").strip()
                cur_price = row.get("current_price", "").strip()

                if not asset_class or not symbol or qty <= 0:
                    errors.append(f"Row {i+2}: invalid data")
                    continue

                from datetime import date as date_type
                parts = acq_date.split("-")
                d = date_type(int(parts[0]), int(parts[1]), int(parts[2]))

                holding = PortfolioHoldingRow(
                    id=str(uuid.uuid4()),
                    investor_id=investor_id,
                    asset_class=asset_class,
                    symbol_or_id=symbol,
                    description=desc,
                    quantity=qty,
                    acquisition_date=d,
                    acquisition_price=acq_price,
                    current_price=float(cur_price) if cur_price else None,
                    notes=notes or None,
                    active=True,
                    created_at=now,
                    updated_at=now,
                )
                self._session.add(holding)
                added += 1
            except Exception as e:
                errors.append(f"Row {i+2}: {str(e)[:80]}")

        await self._session.flush()
        if added > 0:
            await self._log_edit(
                investor_id, None, "import_csv", None, None,
                f"{added} holdings imported",
                detail=f"CSV import: {added} added, {len(errors)} errors",
            )
        return {"added": added, "errors": errors}

    # ── Valuation ──

    async def get_portfolio_summary(self, investor_id: str) -> PortfolioSummary:
        """Get full portfolio with live valuations."""
        # Fetch holdings
        stmt = (
            select(PortfolioHoldingRow)
            .where(PortfolioHoldingRow.investor_id == investor_id, PortfolioHoldingRow.active == True)
            .order_by(PortfolioHoldingRow.asset_class, PortfolioHoldingRow.description)
        )
        result = await self._session.execute(stmt)
        rows = list(result.scalars().all())

        # Get portfolio lifecycle state
        state = await self.get_or_create_state(investor_id)

        if not rows:
            return PortfolioSummary(
                investor_id=investor_id,
                portfolio_status=state.status,
                portfolio_version=state.version,
                onboarding_type=state.onboarding_type,
                frozen_at=state.frozen_at.isoformat() if state.frozen_at else None,
                frozen_by=state.frozen_by,
            )

        # Fetch latest market prices
        stock_prices = await self._get_latest_stock_prices()
        mf_navs = await self._get_latest_mf_navs()
        commodity_prices = await self._get_latest_commodity_prices()
        crypto_prices = await self._get_latest_crypto_prices()

        # Compute valuations
        holdings: list[HoldingResponse] = []
        total_invested = 0.0
        total_current = 0.0
        allocation_map: dict[str, dict] = defaultdict(lambda: {"value": 0.0, "cost": 0.0, "count": 0})

        for row in rows:
            cost = row.quantity * row.acquisition_price
            current_price = self._resolve_price(
                row.asset_class, row.symbol_or_id, row.current_price,
                row.acquisition_price, stock_prices, mf_navs, commodity_prices, crypto_prices
            )
            current_value = row.quantity * current_price if current_price else cost
            gain = current_value - cost
            gain_pct = (gain / cost * 100) if cost > 0 else 0.0

            h = HoldingResponse(
                id=row.id,
                investor_id=row.investor_id,
                asset_class=row.asset_class,
                asset_class_label=ASSET_CLASS_LABELS.get(row.asset_class, row.asset_class),
                symbol_or_id=row.symbol_or_id,
                description=row.description,
                quantity=row.quantity,
                acquisition_date=row.acquisition_date,
                acquisition_price=row.acquisition_price,
                cost_value=round(cost, 2),
                current_price=round(current_price, 2) if current_price else None,
                current_value=round(current_value, 2),
                gain_loss=round(gain, 2),
                gain_loss_pct=round(gain_pct, 2),
                notes=row.notes,
            )
            holdings.append(h)
            total_invested += cost
            total_current += current_value
            allocation_map[row.asset_class]["value"] += current_value
            allocation_map[row.asset_class]["cost"] += cost
            allocation_map[row.asset_class]["count"] += 1

        # Build allocation
        allocation = []
        for ac, data in sorted(allocation_map.items(), key=lambda x: -x[1]["value"]):
            pct = (data["value"] / total_current * 100) if total_current > 0 else 0
            allocation.append(AllocationItem(
                asset_class=ac,
                label=ASSET_CLASS_LABELS.get(ac, ac),
                current_value=round(data["value"], 2),
                cost_value=round(data["cost"], 2),
                percentage=round(pct, 1),
                holdings_count=data["count"],
            ))

        total_gain = total_current - total_invested
        total_gain_pct = (total_gain / total_invested * 100) if total_invested > 0 else 0

        # Get investor name
        investor_name = ""
        try:
            r = await self._session.execute(text("SELECT name FROM investors WHERE id = :id"), {"id": investor_id})
            row = r.one_or_none()
            if row:
                investor_name = row[0]
        except Exception:
            pass

        return PortfolioSummary(
            investor_id=investor_id,
            investor_name=investor_name,
            portfolio_status=state.status,
            portfolio_version=state.version,
            onboarding_type=state.onboarding_type,
            frozen_at=state.frozen_at.isoformat() if state.frozen_at else None,
            frozen_by=state.frozen_by,
            total_invested=round(total_invested, 2),
            current_value=round(total_current, 2),
            total_gain_loss=round(total_gain, 2),
            total_gain_loss_pct=round(total_gain_pct, 2),
            holdings_count=len(holdings),
            asset_classes_count=len(allocation),
            allocation=allocation,
            holdings=holdings,
        )

    def _resolve_price(
        self, asset_class: str, symbol: str, manual_price: float | None,
        acq_price: float,
        stock_prices: dict, mf_navs: dict, commodity_prices: dict, crypto_prices: dict,
    ) -> float:
        """Resolve current price from market data or manual entry."""
        if asset_class == "equity":
            return stock_prices.get(symbol, manual_price or acq_price)
        elif asset_class == "mutual_fund":
            return mf_navs.get(symbol, manual_price or acq_price)
        elif asset_class in ("gold", "silver"):
            mapped = {"gold": "GOLD", "silver": "SILVER"}
            return commodity_prices.get(mapped.get(asset_class, ""), manual_price or acq_price)
        elif asset_class == "crypto":
            return crypto_prices.get(symbol, manual_price or acq_price)
        else:
            # FD, bond, PMS, AIF, real estate, insurance — use manual or acquisition
            return manual_price or acq_price

    async def _get_latest_stock_prices(self) -> dict[str, float]:
        try:
            # Use cache table (instant) with fallback to full scan
            sql = text("SELECT symbol, adj_close FROM latest_stock_prices")
            result = await self._session.execute(sql)
            return {r[0]: r[1] for r in result.all()}
        except Exception:
            try:
                sql = text("SELECT s.symbol, s.adj_close FROM stock_prices s INNER JOIN (SELECT symbol, MAX(date) as md FROM stock_prices GROUP BY symbol) m ON s.symbol = m.symbol AND s.date = m.md")
                result = await self._session.execute(sql)
                return {r[0]: r[1] for r in result.all()}
            except Exception:
                return {}

    async def _get_latest_mf_navs(self) -> dict[str, float]:
        try:
            # Use cache table (instant) with fallback to full scan
            sql = text("SELECT scheme_code, nav FROM latest_mf_navs")
            result = await self._session.execute(sql)
            return {r[0]: r[1] for r in result.all()}
        except Exception:
            try:
                sql = text("SELECT n.scheme_code, n.nav FROM mf_navs n INNER JOIN (SELECT scheme_code, MAX(date) as md FROM mf_navs GROUP BY scheme_code) m ON n.scheme_code = m.scheme_code AND n.date = m.md")
                result = await self._session.execute(sql)
                return {r[0]: r[1] for r in result.all()}
            except Exception:
                return {}

    async def _get_latest_commodity_prices(self) -> dict[str, float]:
        try:
            sql = text("SELECT commodity, price_usd FROM latest_commodity_prices")
            result = await self._session.execute(sql)
            return {r[0]: r[1] for r in result.all()}
        except Exception:
            try:
                sql = text("SELECT c.commodity, c.price_usd FROM commodity_prices c INNER JOIN (SELECT commodity, MAX(date) as md FROM commodity_prices GROUP BY commodity) m ON c.commodity = m.commodity AND c.date = m.md")
                result = await self._session.execute(sql)
                return {r[0]: r[1] for r in result.all()}
            except Exception:
                return {}

    async def _get_latest_crypto_prices(self) -> dict[str, float]:
        try:
            sql = text("SELECT coin_id, price_usd FROM latest_crypto_prices")
            result = await self._session.execute(sql)
            return {r[0]: r[1] for r in result.all()}
        except Exception:
            try:
                sql = text("SELECT c.coin_id, c.price_usd FROM crypto_prices c INNER JOIN (SELECT coin_id, MAX(date) as md FROM crypto_prices GROUP BY coin_id) m ON c.coin_id = m.coin_id AND c.date = m.md")
                result = await self._session.execute(sql)
                return {r[0]: r[1] for r in result.all()}
            except Exception:
                return {}

    def _to_response(self, row: PortfolioHoldingRow) -> HoldingResponse:
        cost = row.quantity * row.acquisition_price
        return HoldingResponse(
            id=row.id,
            investor_id=row.investor_id,
            asset_class=row.asset_class,
            asset_class_label=ASSET_CLASS_LABELS.get(row.asset_class, row.asset_class),
            symbol_or_id=row.symbol_or_id,
            description=row.description,
            quantity=row.quantity,
            acquisition_date=row.acquisition_date,
            acquisition_price=row.acquisition_price,
            cost_value=round(cost, 2),
            current_price=row.current_price,
            current_value=row.current_value,
            gain_loss=row.gain_loss,
            gain_loss_pct=row.gain_loss_pct,
            notes=row.notes,
        )
