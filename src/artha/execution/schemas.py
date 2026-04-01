"""API schemas for the Execution layer."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(str, Enum):
    PENDING = "pending"
    FILLED = "filled"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class SubmitOrderRequest(BaseModel):
    decision_id: str
    symbol: str
    side: OrderSide
    quantity: float
    target_weight: float | None = None


class OrderResponse(BaseModel):
    id: str
    decision_id: str
    symbol: str
    side: OrderSide
    quantity: float
    target_weight: float | None = None
    status: OrderStatus
    broker_response: str | None = None
    created_at: datetime
    executed_at: datetime | None = None


class KillSwitchStatus(BaseModel):
    enabled: bool
    toggled_at: datetime | None = None
    toggled_by: str | None = None
