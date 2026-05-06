#!/usr/bin/env python3
"""Cluster 5 chunk 5.6 — demo seed CLI.

Loads / resets the cluster-5 demo seed cohort against a local DB
without going through HTTP. The REST endpoints under
``/api/v2/admin/seed/`` give the same surface to the front-end; this
CLI is a convenience for terminal use.

Usage:

  python -m scripts.seed_v2 status
  python -m scripts.seed_v2 load
  python -m scripts.seed_v2 reset

Permissions: synthesises a CIO actor in-process (the seed_loader
double-checks ``actor.role == CIO``). The CLI is a privileged tool —
keep it out of production runbooks unless you control the environment.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy.ext.asyncio import async_sessionmaker

# Import side-effects to register every ORM table on Base.metadata.
import artha.api_v2.auth.models  # noqa: F401
import artha.api_v2.c0.models  # noqa: F401
import artha.api_v2.cases.models  # noqa: F401
import artha.api_v2.d0.industry.models  # noqa: F401
import artha.api_v2.d0.instruments.models  # noqa: F401
import artha.api_v2.d0.macro.models  # noqa: F401
import artha.api_v2.d0.models  # noqa: F401
import artha.api_v2.investors.models  # noqa: F401
import artha.api_v2.llm.models  # noqa: F401
import artha.api_v2.m1.models  # noqa: F401
import artha.api_v2.m2.models  # noqa: F401
import artha.api_v2.observability.models  # noqa: F401
from artha.api_v2.auth.user_context import Role, UserContext
from artha.api_v2.cases import seed_loader
from artha.common.db.session import get_engine


def _make_cio_actor() -> UserContext:
    return UserContext(
        user_id="cio1",
        firm_id="demo-firm-001",
        role=Role.CIO,
        email="cio1@demo.test",
        name="Demo CIO",
        session_id="seed-cli",
    )


async def _run(action: str) -> int:
    engine = get_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        actor = _make_cio_actor()

        if action == "status":
            status = await seed_loader.get_status(session)
            print(f"Seed loaded: {status.is_loaded}")
            for k, v in sorted(status.counts.items()):
                print(f"  {k}: {v}")
            return 0

        if action == "load":
            try:
                async with session.begin():
                    result = await seed_loader.load_demo_seed(session, actor=actor)
            except seed_loader.SeedAlreadyLoadedError as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                print("Hint: run `seed_v2 reset` first.", file=sys.stderr)
                return 2
            except seed_loader.SeedFrameworkError as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 1
            print("Seed load complete:")
            print(f"  households: {result.households}")
            print(f"  investors:  {result.investors}")
            print(f"  mandates:   {result.mandates}")
            print(f"  cases:      {result.cases}")
            return 0

        if action == "reset":
            try:
                async with session.begin():
                    result = await seed_loader.reset_demo_seed(session, actor=actor)
            except seed_loader.SeedFrameworkError as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 1
            print("Seed reset complete:")
            print(f"  cases deleted:           {result.cases_deleted}")
            print(f"  mandates deleted:        {result.mandates_deleted}")
            print(f"  mandate versions:        {result.mandate_versions_deleted}")
            print(f"  investors deleted:       {result.investors_deleted}")
            print(f"  households deleted:      {result.households_deleted}")
            print(f"  snapshots deleted:       {result.snapshots_deleted}")
            print(f"  stage rows deleted:      {result.stage_rows_deleted}")
            return 0

    print(f"Unknown action: {action!r}", file=sys.stderr)
    return 64


def main() -> int:
    parser = argparse.ArgumentParser(prog="seed_v2", description=__doc__)
    parser.add_argument("action", choices=["status", "load", "reset"])
    args = parser.parse_args()
    return asyncio.run(_run(args.action))


if __name__ == "__main__":
    sys.exit(main())
