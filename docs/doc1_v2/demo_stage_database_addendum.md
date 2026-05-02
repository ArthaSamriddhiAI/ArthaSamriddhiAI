# Samriddhi AI: Demo-Stage Database Addendum

## SQLite for Demo Stage; Postgres Deferred to Production-Readiness

**Document:** Samriddhi AI, Demo-Stage Database Addendum
**Scope:** All clusters during internal demo stage
**Status:** Active for internal demo stage; superseded when production-readiness phase begins
**Date:** April 2026
**Authors:** Shubham Sahamate, with consolidation support from Claude Opus 4.7 Adaptive

---

## 0. Document Purpose

This addendum modifies the database choice for Samriddhi AI during the internal demo stage. The principles of operation document and the cluster 0 specifications inherited Postgres as the database from the Doc 1 v1 production architecture. For demo stage, where the system runs on a single laptop with a single user at a time, Postgres adds operational overhead without unlocking capability.

This addendum carves out a demo-stage exception: SQLite via SQLAlchemy 2.0 async is the active database for demo. The production specification (Postgres 16) is preserved unchanged; the implementation diverges for demo and converges with the spec when production-readiness phase begins.

This is the same pattern as the cluster 0 dev-mode addendum for stub authentication: production rigor preserved in the spec, demo simplicity in the implementation, focused migration cluster when production matters.

---

## 1. What This Addendum Changes

### 1.1 Active Database for Demo Stage

The demo stage runs SQLite as the application database. Connection string in the deployment's environment configuration points at a local SQLite file (e.g., `sqlite+aiosqlite:///./samriddhi_dev.db`).

The SQLAlchemy 2.0 async ORM layer abstracts the database; application code does not need database-specific changes when SQLite is the backend instead of Postgres, provided the application sticks to standard ORM operations.

### 1.2 Alembic Migrations

Alembic migrations target SQLite during demo stage. Migrations should be authored to be portable: avoid Postgres-specific column types (`JSONB`, `ARRAY`, `TSVECTOR`), avoid Postgres-specific indexes (GIN, GIST), avoid Postgres-specific extensions (pgvector, hstore).

The standard SQLAlchemy `JSON` type works on both SQLite and Postgres (stored as TEXT on SQLite, native JSONB on Postgres). Use `JSON` rather than `JSONB`.

When the production-readiness migration cluster runs, Alembic migrations are re-targeted to Postgres. Most migrations should be unchanged; any that are Postgres-specific or SQLite-specific are flagged during that cluster.

### 1.3 SQLAlchemy Driver

The async driver for SQLite is `aiosqlite`. Add it to `requirements.txt` alongside (or instead of) `asyncpg`. Both can be installed; the application uses whichever the connection string indicates.

```
# In requirements.txt for demo stage:
sqlalchemy[asyncio]==2.0.x
aiosqlite==0.19.x
# asyncpg deferred until production-readiness
```

### 1.4 Database File Location

The SQLite database file lives in the project root or a dedicated `data/` folder. It is excluded from Git (`.gitignore` entry: `&#42;.db`). Each developer has their own local database file; resetting the database means deleting the file and rerunning migrations.

For demo stage, this is the right tradeoff: simplicity over operational sophistication. Each developer (and each demo session) starts from a clean database state.

---

## 2. What This Addendum Does Not Change

### 2.1 Application Code Targeting SQLAlchemy ORM

Application code throughout the system targets the SQLAlchemy ORM. As long as code uses standard ORM operations (`select()`, `insert()`, relationship loading, async sessions), it runs on both SQLite and Postgres without modification. This is the architectural property that makes the demo-to-production database swap a focused migration rather than a rewrite.

### 2.2 Schema Definitions

Schema definitions in SQLAlchemy declarative models are unchanged. The same model definitions (the `User`, `Session`, `Investor`, `Mandate`, `Case`, `Holding`, `MandateVersion`, all of them) work on SQLite and Postgres.

### 2.3 Data Layer Architecture

D0's architecture (FR Entry 10.0 onwards) is unchanged. The snapshot assembler, the staging tables, the normalization layer, the freshness SLA all work on SQLite for demo stage. They will work on Postgres for production. No D0 component is database-specific.

### 2.4 Telemetry, Sessions, Cases

T1 telemetry, sessions table, case object schema, all the canonical entity tables are unchanged. They are SQLAlchemy models. Where they live (SQLite file vs Postgres database) is config, not architecture.

---

## 3. Demo-Stage Limitations of SQLite

### 3.1 Single-Process Writes

SQLite serialises writes through a single global lock. Multi-process FastAPI workers (e.g., uvicorn with multiple workers, or gunicorn with multiple processes) will contend on the lock. For demo stage running single-worker uvicorn, this is fine. For production with multi-worker deployments, Postgres is required.

The development setup runs `uvicorn main:app --reload` which is single-worker by default. Demo stage relies on this; no configuration change needed.

### 3.2 No Network Database Access

SQLite is file-based, accessed through the local filesystem. Multiple machines cannot share a SQLite database. For demo stage running on one laptop, this is irrelevant. For production deployment where the application server and database may be on different machines, Postgres is required.

### 3.3 Limited JSON Operations

SQLite supports basic JSON via the `json1` extension (built into modern SQLite), including extracting fields and updating them. Postgres has richer JSON operations (JSONB indexes, JSONB containment operators, JSONB path queries). Demo stage code should not rely on advanced JSON operations; if a query genuinely needs Postgres JSON features, it gets specced for the production-readiness phase.

In practice, agent verdicts, case bundles, and other JSON-heavy structures are stored as JSON columns and read whole into Python objects rather than queried inside the database. This pattern works on both SQLite and Postgres.

### 3.4 No Foreign Key Constraints by Default

SQLite has foreign key constraints but they are off by default. SQLAlchemy can enable them via a connection event:

```python
from sqlalchemy import event
@event.listens_for(engine.sync_engine, "connect")
def enable_foreign_keys(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()
```

This snippet is part of the demo stage SQLAlchemy configuration. Postgres has foreign keys enabled by default; this configuration is SQLite-specific.

### 3.5 No pgvector or Equivalent

If a future cluster decides RAG retrieval is needed (the principles document defers this; the door is open), the embedding storage requires pgvector or equivalent. SQLite has no equivalent extension built-in. If RAG is added during demo stage, the embedding storage uses an external file-based vector store (e.g., FAISS index files); when production-readiness phase begins, that swaps to pgvector inside the production Postgres.

This is unlikely to be needed during demo stage, but documented for completeness.

---

## 4. Migration Path to Production

When the project transitions out of internal demo stage to production-readiness, the database migration is part of the production-readiness cluster (likely the same cluster that handles the auth migration from stub to real OIDC). The migration consists of:

### 4.1 Install Postgres

The production deployment provisions Postgres 16 per Doc 4 Operations. Connection details are configured per deployment.

### 4.2 Update Connection String

The application's environment configuration changes from `sqlite+aiosqlite:///./samriddhi_dev.db` to `postgresql+asyncpg://user:pass@host:port/dbname`.

### 4.3 Install asyncpg

Add `asyncpg` to `requirements.txt`. Optionally remove `aiosqlite` if SQLite is no longer needed.

### 4.4 Re-run Alembic Migrations Against Postgres

`alembic upgrade head` runs against the new Postgres connection. Migrations should run cleanly because they were authored portably (per §1.2).

### 4.5 Migrate Data (If Needed)

For demo stage, no data migration is needed; production starts fresh. If specific demo data needs to be preserved (test cases, demo investors, configured policies), a small data migration script copies records from the SQLite database to the new Postgres database via SQLAlchemy. This is straightforward because the schema is identical.

### 4.6 Remove SQLite-Specific Configuration

The foreign-key-enabling connection event from §3.4 can be removed (Postgres has FK enforcement built-in). Any other SQLite-specific configuration is removed.

### 4.7 Validate Application Functionality

Run the full test suite against Postgres. Any test that was passing on SQLite should pass on Postgres; if any fails, investigate (likely a portability issue in a query that needs fixing).

This migration is bounded: a focused half-day to a day of work. Most of the time is on the operations side (provisioning Postgres, configuring secrets); the application side is config plus migration rerun.

---

## 5. Acceptance Criteria for This Addendum

The addendum is considered correctly applied when:

1. The application's environment configuration uses a SQLite connection string for demo stage (e.g., `sqlite+aiosqlite:///./samriddhi_dev.db`).
2. `requirements.txt` includes `aiosqlite` and SQLAlchemy 2.0 with async support.
3. Alembic migrations run successfully against SQLite via `alembic upgrade head`.
4. Foreign key constraints are enabled at the SQLite connection level (per §3.4).
5. Application code uses standard SQLAlchemy ORM operations and does not depend on Postgres-specific features.
6. The SQLite database file is excluded from Git via `.gitignore`.
7. Cluster 0 implementation works end-to-end against SQLite: auth (with stub login per the dev-mode addendum), session creation, refresh, logout, SSE connection, T1 telemetry events all functional.

---

## 6. Cross-Reference Updates

Other documents in the Doc 1 v2 stack reference Postgres explicitly. Those references stand as production specifications; this addendum is the demo-stage carve-out. The references that matter:

**Principles of Operation §4.4 (No Vector DB in MVP):** Mentions "pgvector inside the existing Postgres" as the deferred-to-v2 retrieval option. Demo stage reads this as: "if RAG is needed during demo, use FAISS or similar file-based vector store; pgvector becomes the option only when production Postgres is in place."

**Cluster 0 Ideation Log §6.1 (Backend Stack Confirmation):** Mentions "Python 3.12, FastAPI, SQLAlchemy 2.0 async, PostgreSQL 16." Demo stage reads this as: "PostgreSQL 16 in production; SQLite via aiosqlite in demo stage."

**FR Entry 17.1 §3.2 (Session State):** Describes the sessions table schema. This schema works on both SQLite and Postgres. Demo stage uses it on SQLite; production uses it on Postgres.

**FR Entry 10.0 onwards (D0 Data Layer):** D0 components store records in canonical entity tables. These work on SQLite for demo; production migration is part of the production-readiness cluster.

When the production-readiness cluster runs, this addendum is marked superseded and these cross-references become active production specifications without further mediation.

---

## 7. Revision History

April 2026 (demo-stage database addendum authoring): Initial addendum created. Active for internal demo stage. Will be superseded when production-readiness phase begins.

---

**End of Demo-Stage Database Addendum.**
