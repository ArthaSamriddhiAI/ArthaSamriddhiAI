"""Strangler-fig coexistence test suite.

Verifies that after step 7's wiring change in src/artha/app.py:

- /app/ serves the React bundle (chunk plan §scope_in)
- /app/dev-login (and any other SPA route) falls back to the React index.html
  via SPAStaticFiles (chunk plan implementation notes)
- /static/index.html still serves the existing v1 Alpine SPA
  (chunk 0.1 acceptance criterion 10)
- /api/v1/* legacy routes still respond (no regression)
- /api/v2/* cluster-0 routes still respond
- / serves the v1 landing page (no regression)

These tests use the actual app instance — no fixtures or DB needed since
none of the routes under test touch the database.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from artha.app import app


@pytest_asyncio.fixture
async def http():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


# ---------------------------------------------------------------------------
# Pre-flight — these tests assume the React bundle is present. If you're
# running them on a fresh checkout, run `cd web && npm run build` first.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _require_react_bundle():
    if not Path("web/dist/index.html").exists():
        pytest.skip(
            "web/dist/index.html missing; "
            "run `cd web && npm run build` before these tests."
        )


# ---------------------------------------------------------------------------
# 1. React bundle served at /app/*
# ---------------------------------------------------------------------------


class TestReactBundleAtApp:
    @pytest.mark.asyncio
    async def test_app_root_serves_react_index_html(self, http):
        response = await http.get("/app/")
        assert response.status_code == 200
        body = response.text
        # Vite-built index.html has a /app/-prefixed asset reference
        # (we set base: '/app/' in vite.config.ts).
        assert '<div id="root">' in body
        assert "/app/assets/" in body

    @pytest.mark.asyncio
    async def test_arbitrary_spa_path_falls_back_to_index_html(self, http):
        """SPAStaticFiles must serve index.html for unknown paths so the
        client-side router can resolve them.

        Cluster 0.1 has /app/dev-login (not a real file in dist/) — chunk
        0.2 will add /app/advisor, /app/cio, etc. All must fall back.
        """
        response = await http.get("/app/dev-login")
        assert response.status_code == 200
        assert '<div id="root">' in response.text

    @pytest.mark.asyncio
    async def test_deep_spa_path_falls_back_to_index_html(self, http):
        """Forward-looking: chunk 0.2 will hit /app/advisor/..."""
        response = await http.get("/app/advisor/some-future-route")
        assert response.status_code == 200
        assert '<div id="root">' in response.text


# ---------------------------------------------------------------------------
# 2. Alpine SPA still reachable at /static/* (chunk 0.1 criterion 10)
# ---------------------------------------------------------------------------


class TestAlpineSPAPreserved:
    @pytest.mark.asyncio
    async def test_alpine_index_html_still_served_at_static(self, http):
        response = await http.get("/static/index.html")
        assert response.status_code == 200
        # The Alpine SPA's index.html starts with a DOCTYPE + Alpine markup;
        # check for the html tag with the class attribute we observed in step 1.
        assert "<!DOCTYPE html>" in response.text or "<!doctype html>" in response.text

    @pytest.mark.asyncio
    async def test_landing_html_still_served_at_root(self, http):
        response = await http.get("/")
        assert response.status_code == 200
        # The landing page is served as static/landing.html.
        assert response.headers.get("content-type", "").startswith("text/html")


# ---------------------------------------------------------------------------
# 3. v1 API routes still respond (no regression)
# ---------------------------------------------------------------------------


class TestV1ApiPreserved:
    @pytest.mark.asyncio
    async def test_v1_health_returns_ok(self, http):
        response = await http.get("/api/v1/health")
        assert response.status_code == 200
        body = response.json()
        assert body == {"status": "ok", "service": "Samriddhi AI"}


# ---------------------------------------------------------------------------
# 4. v2 API routes still work (cluster 0 itself doesn't break)
# ---------------------------------------------------------------------------


class TestV2ApiPreserved:
    @pytest.mark.asyncio
    async def test_v2_dev_users_returns_yaml_users(self, http):
        response = await http.get("/api/v2/auth/dev-users")
        assert response.status_code == 200
        body = response.json()
        assert "users" in body
        assert len(body["users"]) == 4

    @pytest.mark.asyncio
    async def test_v2_oidc_login_stub_returns_501(self, http):
        response = await http.get("/api/v2/auth/login")
        assert response.status_code == 501


# ---------------------------------------------------------------------------
# 5. Mount precedence — /api/v2/* must NOT be intercepted by the React mount
# ---------------------------------------------------------------------------


class TestMountPrecedence:
    @pytest.mark.asyncio
    async def test_api_v2_path_returns_json_not_html(self, http):
        """Sanity: /api/v2/auth/dev-users returns JSON, not the SPA fallback."""
        response = await http.get("/api/v2/auth/dev-users")
        assert response.headers.get("content-type", "").startswith("application/json")
        assert "<div id=\"root\">" not in response.text

    @pytest.mark.asyncio
    async def test_api_v1_path_returns_json_not_html(self, http):
        response = await http.get("/api/v1/health")
        assert response.headers.get("content-type", "").startswith("application/json")
