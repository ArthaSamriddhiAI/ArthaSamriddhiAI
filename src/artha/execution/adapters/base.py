"""Execution adapter protocol — dumb, constrained, firewalled."""

from __future__ import annotations

from typing import Any, Protocol


class ExecutionResult:
    def __init__(self, success: bool, order_id: str, message: str = "") -> None:
        self.success = success
        self.order_id = order_id
        self.message = message


class ExecutionAdapter(Protocol):
    """Protocol for execution adapters. Zero discretion."""

    async def submit_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        **kwargs: Any,
    ) -> ExecutionResult: ...

    async def cancel_order(self, order_id: str) -> ExecutionResult: ...
