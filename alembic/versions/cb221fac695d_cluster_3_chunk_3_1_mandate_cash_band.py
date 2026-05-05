"""cluster_3_chunk_3_1_mandate_cash_band

Adds the cluster 3 cash band to ``v2_mandate_versions``:

* ``cash_min_pct`` and ``cash_max_pct`` (integer, default 0).
* Bumps ``schema_version`` to 2 for newly-created records (existing
  records keep their stored value; the application's create path stamps
  schema_version=2 going forward).

Per FR Entry 10.7 §10 + cluster 3 ideation §8.3: existing records get
``cash_min_pct=0`` and ``cash_max_pct=0`` so pre-revision behaviour is
preserved as closely as possible (the cash portion was implicitly captured
by ``liquidity_floor_pct`` in cluster 2).

Revision ID: cb221fac695d
Revises: 55f44b4363e0 (cluster 3 chunk 3.1 D0 framework)
Create Date: 2026-05-05
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "cb221fac695d"
down_revision: Union[str, Sequence[str], None] = "55f44b4363e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add columns with server_default=0 so existing rows get populated
    # cleanly. Drop the server default afterwards so the application
    # always supplies the value going forward.
    op.add_column(
        "v2_mandate_versions",
        sa.Column(
            "cash_min_pct",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "v2_mandate_versions",
        sa.Column(
            "cash_max_pct",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )

    # SQLite (cluster 3 demo DB) doesn't support ALTER COLUMN to drop a
    # default. The server_default stays in the schema; the application
    # always supplies the value on inserts so it never fires in practice.
    # On Postgres deployments the default would be dropped via:
    #   op.alter_column("v2_mandate_versions", "cash_min_pct", server_default=None)
    #   op.alter_column("v2_mandate_versions", "cash_max_pct", server_default=None)


def downgrade() -> None:
    op.drop_column("v2_mandate_versions", "cash_max_pct")
    op.drop_column("v2_mandate_versions", "cash_min_pct")
