"""Pre-trade risk checks — validates orders before execution."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PreTradeCheckResult(BaseModel):
    passed: bool
    checks: list[str] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)


class PreTradeChecker:
    """Validates orders against position limits before execution."""

    def __init__(
        self,
        max_order_value: float = 1_000_000,
        max_single_order_pct: float = 0.10,
        portfolio_value: float = 10_000_000,
    ) -> None:
        self._max_order_value = max_order_value
        self._max_single_order_pct = max_single_order_pct
        self._portfolio_value = portfolio_value

    def check(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
    ) -> PreTradeCheckResult:
        checks = []
        failures = []

        # Check 1: Order value limit
        order_value = quantity * price
        if order_value <= self._max_order_value:
            checks.append(f"Order value {order_value:.2f} within limit {self._max_order_value:.2f}")
        else:
            failures.append(
                f"Order value {order_value:.2f} exceeds limit {self._max_order_value:.2f}"
            )

        # Check 2: Portfolio percentage
        if self._portfolio_value > 0:
            pct = order_value / self._portfolio_value
            if pct <= self._max_single_order_pct:
                checks.append(f"Order {pct:.2%} of portfolio within {self._max_single_order_pct:.2%} limit")
            else:
                failures.append(
                    f"Order {pct:.2%} of portfolio exceeds {self._max_single_order_pct:.2%} limit"
                )

        # Check 3: Quantity sanity
        if quantity > 0:
            checks.append("Quantity is positive")
        else:
            failures.append("Quantity must be positive")

        return PreTradeCheckResult(
            passed=len(failures) == 0,
            checks=checks,
            failures=failures,
        )
