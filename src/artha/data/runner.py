"""CLI entry point for data pipeline execution."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from artha.common.db.base import Base


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("artha.pipeline")


async def _run(args: argparse.Namespace) -> None:
    # Import models to register them with Base
    import artha.data.models  # noqa: F401
    import artha.evidence.models  # noqa: F401
    import artha.governance.models  # noqa: F401
    import artha.accountability.models  # noqa: F401
    import artha.execution.models  # noqa: F401

    db_url = args.db_url
    engine = create_async_engine(db_url, echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        # Refresh universe
        if args.refresh_universe:
            from artha.data.universe import refresh_nifty500
            log.info("=== Refreshing Nifty 500 universe ===")
            added = await refresh_nifty500(session)
            await session.commit()
            log.info(f"Universe refresh done: {added} new symbols")

        # Seed MF schemes
        if args.seed_mf or args.mf:
            from artha.data.universe import seed_mf_schemes
            log.info("=== Seeding MF scheme universe ===")
            added = await seed_mf_schemes(session)
            await session.commit()
            log.info(f"MF schemes seeded: {added} new")

        # Stock pipeline
        if args.stocks:
            from artha.data.stock_pipeline import run_stock_pipeline
            log.info("=== Running stock price pipeline ===")
            run_id = await run_stock_pipeline(session, initial=args.initial)
            await session.commit()
            log.info(f"Stock pipeline run: {run_id}")

        # MF pipeline
        if args.mf:
            from artha.data.mf_pipeline import run_mf_pipeline
            log.info("=== Running MF NAV pipeline ===")
            run_id = await run_mf_pipeline(session, initial=args.initial)
            await session.commit()
            log.info(f"MF pipeline run: {run_id}")

    await engine.dispose()
    log.info("=== Pipeline execution complete ===")


def main() -> None:
    parser = argparse.ArgumentParser(description="ArthaSamriddhiAI Data Pipeline")
    parser.add_argument("--stocks", action="store_true", help="Run stock price pipeline")
    parser.add_argument("--mf", action="store_true", help="Run mutual fund NAV pipeline")
    parser.add_argument("--initial", action="store_true", help="Full 10-year backfill (default: incremental)")
    parser.add_argument("--refresh-universe", action="store_true", help="Refresh Nifty 500 constituent list")
    parser.add_argument("--seed-mf", action="store_true", help="Seed top 50 MF schemes")
    parser.add_argument(
        "--db-url",
        default="sqlite+aiosqlite:///./artha.db",
        help="Database URL (default: sqlite)",
    )
    args = parser.parse_args()

    if not any([args.stocks, args.mf, args.refresh_universe, args.seed_mf]):
        parser.print_help()
        sys.exit(1)

    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
