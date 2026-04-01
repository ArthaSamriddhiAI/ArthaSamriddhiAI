"""Emergency kill switch — global toggle to halt all execution."""

from __future__ import annotations

from datetime import datetime

from artha.common.clock import get_clock
from artha.common.errors import ExecutionHaltedError
from artha.execution.schemas import KillSwitchStatus


class KillSwitch:
    """Global execution kill switch. When active, all order submission is blocked."""

    def __init__(self) -> None:
        self._active = False
        self._toggled_at: datetime | None = None
        self._toggled_by: str | None = None

    @property
    def is_active(self) -> bool:
        return self._active

    def activate(self, by: str = "system") -> None:
        self._active = True
        self._toggled_at = get_clock().now()
        self._toggled_by = by

    def deactivate(self, by: str = "system") -> None:
        self._active = False
        self._toggled_at = get_clock().now()
        self._toggled_by = by

    def check(self) -> None:
        """Raise if kill switch is active."""
        if self._active:
            raise ExecutionHaltedError()

    def status(self) -> KillSwitchStatus:
        return KillSwitchStatus(
            enabled=self._active,
            toggled_at=self._toggled_at,
            toggled_by=self._toggled_by,
        )


# Singleton
kill_switch = KillSwitch()
