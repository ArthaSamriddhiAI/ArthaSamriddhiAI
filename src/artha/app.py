"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI

from artha.common.db.base import Base
from artha.common.db.engine import get_engine, dispose_engine
from artha.evidence.router import router as evidence_router
from artha.governance.router import router as governance_router
from artha.accountability.router import router as accountability_router
from artha.execution.router import router as execution_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Startup: create all tables
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # Shutdown
    await dispose_engine()


def create_app() -> FastAPI:
    app = FastAPI(
        title="ArthaSamriddhiAI",
        description="Portfolio Operating System — Evidence, Governance, Accountability",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Register routers
    app.include_router(evidence_router, prefix="/api/v1")
    app.include_router(governance_router, prefix="/api/v1")
    app.include_router(accountability_router, prefix="/api/v1")
    app.include_router(execution_router, prefix="/api/v1")

    @app.get("/api/v1/health")
    async def health():
        return {"status": "ok", "service": "ArthaSamriddhiAI"}

    return app


app = create_app()
