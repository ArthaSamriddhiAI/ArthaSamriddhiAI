"""Mock execution adapter for testing."""

from __future__ import annotations

import uuid
from typing import Any

from artha.execution.adapters.base import ExecutionResult


class MockExecutionAdapter:
    """Mock broker — simulates order placement with configurable behavior."""

    def __init__(self, fail_symbols: set[str] | None = None) -> None:
        self._fail_symbols = fail_symbols or set()
        self._orders: dict[str, dict[str, Any]] = {}

    async def submit_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        **kwargs: Any,
    ) -> ExecutionResult:
        order_id = str(uuid.uuid4())

        if symbol in self._fail_symbols:
            return ExecutionResult(
                success=False,
                order_id=order_id,
                message=f"Mock rejection: {symbol} is in fail list",
            )

        self._orders[order_id] = {
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "status": "filled",
            **kwargs,
        }

        return ExecutionResult(
            success=True,
            order_id=order_id,
            message=f"Mock filled: {side} {quantity} {symbol}",
        )

    async def cancel_order(self, order_id: str) -> ExecutionResult:
        if order_id in self._orders:
            self._orders[order_id]["status"] = "cancelled"
            return ExecutionResult(success=True, order_id=order_id, message="Cancelled")
        return ExecutionResult(success=False, order_id=order_id, message="Order not found")
