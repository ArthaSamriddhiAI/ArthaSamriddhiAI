"""Rule persistence and versioning."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from artha.common.clock import get_clock
from artha.common.types import RuleSetVersionID
from artha.governance.models import RuleSetVersionRow
from artha.governance.rules.loader import load_rule_set_from_directory
from artha.governance.rules.models import RuleSet


class RuleRepository:
    def __init__(self, session: AsyncSession, rules_dir: Path) -> None:
        self._session = session
        self._rules_dir = rules_dir
        self._cached_rule_set: RuleSet | None = None

    async def get_active_rule_set(self) -> RuleSet:
        """Get the currently active rule set, loading from YAML if needed."""
        if self._cached_rule_set is None:
            self._cached_rule_set = load_rule_set_from_directory(self._rules_dir)
        return self._cached_rule_set

    async def snapshot_rule_set(self) -> RuleSet:
        """Create a versioned snapshot of the current rule set for audit purposes."""
        rule_set = await self.get_active_rule_set()

        row = RuleSetVersionRow(
            id=rule_set.version_id,
            rules_json=json.dumps([r.model_dump(mode="json") for r in rule_set.rules]),
            created_at=rule_set.created_at,
        )
        self._session.add(row)
        await self._session.flush()

        return rule_set

    async def get_rule_set_version(
        self, version_id: RuleSetVersionID
    ) -> RuleSet | None:
        """Retrieve a historical rule set version."""
        stmt = select(RuleSetVersionRow).where(RuleSetVersionRow.id == version_id)
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            return None

        from artha.governance.rules.models import Rule
        rules = [Rule.model_validate(r) for r in json.loads(row.rules_json)]
        return RuleSet(
            version_id=RuleSetVersionID(row.id),
            rules=rules,
            created_at=row.created_at,
        )

    def invalidate_cache(self) -> None:
        self._cached_rule_set = None
