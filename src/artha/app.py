"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import Scope

# Cluster 0 (api_v2): register ORM tables + auth/events/system routers.
import artha.api_v2.auth.models  # noqa: F401 — register sessions table
import artha.api_v2.observability.models  # noqa: F401 — register t1_events table
# Cluster 1 (api_v2): investor + household tables (v2_ prefix to avoid v1 collision).
import artha.api_v2.c0.models  # noqa: F401 — register v2_c0_conversations + v2_c0_messages (chunk 1.2)
import artha.api_v2.investors.models  # noqa: F401 — register v2_investors + v2_households
import artha.api_v2.llm.models  # noqa: F401 — register v2_llm_provider_config (chunk 1.3)
import artha.data.commodity_pipeline  # noqa: F401 — register commodity tables
import artha.data.crypto_pipeline  # noqa: F401 — register crypto tables
import artha.data.forex_pipeline  # noqa: F401 — register forex tables
import artha.data.macro_pipeline  # noqa: F401 — register macro tables
import artha.data.models  # noqa: F401 — register data pipeline tables
import artha.data.upload  # noqa: F401 — register upload tables
import artha.investor.mandates  # noqa: F401 — register mandate tables
import artha.investor.models  # noqa: F401 — register investor profile tables
import artha.portfolio.goals  # noqa: F401 — register goals table
import artha.portfolio.models  # noqa: F401 — register portfolio tables
from artha.accountability.router import router as accountability_router
from artha.api_v2.auth.router import router as auth_v2_router
from artha.api_v2.events.router import router as events_v2_router
from artha.api_v2.c0.router import router as c0_v2_router
from artha.api_v2.investors.router import router as investors_v2_router
from artha.api_v2.llm.router import router as llm_v2_router
from artha.api_v2.system.firm_info import router as system_firm_info_router
from artha.api_v2.system.role_home import router as system_role_home_router
from artha.common.db.base import Base
from artha.common.db.engine import dispose_engine, get_engine
from artha.data.router import router as data_explorer_router
from artha.data.upload import router as data_upload_router
from artha.evidence.router import router as evidence_router
from artha.execution.router import router as execution_router
from artha.governance.router import router as governance_router
from artha.help.router import router as help_router
from artha.investor.router import router as investor_router
from artha.portfolio.router import router as portfolio_router
from artha.portfolio_analysis.router import router as pam_router

logger = logging.getLogger(__name__)


class SPAStaticFiles(StaticFiles):
    """``StaticFiles`` that falls back to ``index.html`` for unknown paths.

    Cluster 0 chunk plan implementation notes call for this:
    "The catchall fallback for `/app/*` to `/app/index.html` (so client-side
     routing works) is handled by `StaticFiles(html=True)` plus a custom
     404 handler."

    Starlette's ``html=True`` flag only serves ``index.html`` for the mount
    root, not arbitrary unknown paths. For SPA client-side routing
    (``/app/dev-login``, ``/app/advisor`` in chunk 0.2, etc.) we need to
    serve ``index.html`` for ANY unknown path under the mount and let the
    React router resolve it.

    Path-traversal protection (``..`` etc.) is preserved by ``super()``;
    only 404s are caught.
    """

    async def get_response(self, path: str, scope: Scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404:
                return await super().get_response("index.html", scope)
            raise


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
        title="Samriddhi AI",
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
    app.include_router(help_router, prefix="/api/v1")
    app.include_router(pam_router, prefix="/api/v1")

    # Cluster 0 (api_v2): each router carries its own /api/v2/... prefix.
    app.include_router(auth_v2_router)
    app.include_router(events_v2_router)
    app.include_router(system_firm_info_router)
    app.include_router(system_role_home_router)
    # Cluster 1 chunk 1.1: investors + households surface.
    app.include_router(investors_v2_router)
    # Cluster 1 chunk 1.3: SmartLLMRouter settings + kill switch.
    app.include_router(llm_v2_router)
    # Cluster 1 chunk 1.2: C0 conversational onboarding.
    app.include_router(c0_v2_router)

    @app.get("/api/v1/health")
    async def health():
        return {"status": "ok", "service": "Samriddhi AI"}

    # ------------------------------------------------------------------
    # Strangler-fig static mounts — order matters.
    #
    # Per chunk plan §scope_in / implementation notes:
    #   1. /api/* routers come first (already registered above) so API
    #      routes win over any path that might collide.
    #   2. /app/* serves the React bundle from web/dist/ with SPA
    #      fallback (so client-side routing under /app works).
    #   3. /static/* preserves the existing v1 Alpine SPA at
    #      /static/index.html etc. The previous @app.get("/app") that
    #      returned "static/index.html" is REMOVED — bookmarks pointing
    #      at /app now hit the React app, the strangler-fig cutover.
    #
    # Each mount is conditional on its directory existing, so:
    # - If web/dist is absent (no React build done), /app 404s cleanly
    #   instead of crashing the app.
    # - If static/ is absent (rare), the v1 SPA path silently disables.
    # ------------------------------------------------------------------

    react_bundle_dir = Path("web/dist")
    if react_bundle_dir.exists():
        app.mount(
            "/app",
            SPAStaticFiles(directory=str(react_bundle_dir), html=True),
            name="react_app",
        )
    else:
        logger.warning(
            "React bundle directory %s missing; /app/* will 404. "
            "Run `cd web && npm run build` to populate it.",
            react_bundle_dir,
        )

    static_dir = Path("static")
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory="static"), name="static")

        @app.get("/")
        async def root():
            return FileResponse("static/landing.html")

    return app


app = create_app()
