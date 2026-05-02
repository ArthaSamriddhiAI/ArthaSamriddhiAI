"""Async SQLAlchemy engine singleton.

Per Demo-Stage Database Addendum §3.4: when the engine is SQLite, register a
``connect`` event listener that issues ``PRAGMA foreign_keys=ON`` so foreign key
constraints are enforced at the DB level (SQLite ships with FKs disabled by
default; Postgres has them on). The listener is a no-op for non-SQLite engines,
so production Postgres deployments are unaffected.
"""

from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from artha.config import settings

_engine: AsyncEngine | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            settings.database_url,
            echo=(settings.environment.value == "development"),
            json_serializer=None,
        )

        # SQLite-only: enable foreign key enforcement per DB addendum §3.4.
        if _engine.dialect.name == "sqlite":

            @event.listens_for(_engine.sync_engine, "connect")
            def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

    return _engine


async def dispose_engine() -> None:
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
