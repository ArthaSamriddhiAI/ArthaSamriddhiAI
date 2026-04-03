"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from artha.common.db.base import Base
from artha.common.db.engine import get_engine, dispose_engine
import artha.data.models  # noqa: F401 — register data pipeline tables
import artha.data.commodity_pipeline  # noqa: F401 — register commodity tables
import artha.data.forex_pipeline  # noqa: F401 — register forex tables
import artha.data.macro_pipeline  # noqa: F401 — register macro tables
import artha.data.crypto_pipeline  # noqa: F401 — register crypto tables
import artha.data.upload  # noqa: F401 — register upload tables
import artha.investor.models  # noqa: F401 — register investor profile tables
import artha.investor.mandates  # noqa: F401 — register mandate tables
from artha.evidence.router import router as evidence_router
from artha.governance.router import router as governance_router
from artha.accountability.router import router as accountability_router
from artha.execution.router import router as execution_router
from artha.investor.router import router as investor_router
from artha.data.upload import router as data_upload_router
from artha.data.router import router as data_explorer_router
import artha.portfolio.models  # noqa: F401 — register portfolio tables
import artha.portfolio.goals  # noqa: F401 — register goals table
from artha.portfolio.router import router as portfolio_router


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
    app.include_router(investor_router, prefix="/api/v1")
    app.include_router(data_upload_router, prefix="/api/v1")
    app.include_router(data_explorer_router, prefix="/api/v1")
    app.include_router(portfolio_router, prefix="/api/v1")

    @app.get("/api/v1/health")
    async def health():
        return {"status": "ok", "service": "ArthaSamriddhiAI"}

    # Static files and SPA root
    static_dir = Path("static")
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory="static"), name="static")

        @app.get("/")
        async def root():
            return FileResponse("static/landing.html")

        @app.get("/app")
        async def app_root():
            return FileResponse("static/index.html")

    return app


app = create_app()
