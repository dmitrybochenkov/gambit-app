"""allow null tournament fund for closed imports

Revision ID: e6f7a8b9c0d1
Revises: e5f6a7b8c9d0
Create Date: 2026-08-10 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e6f7a8b9c0d1"
down_revision: str | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("tournaments") as batch_op:
        batch_op.drop_constraint("tournament_fund_status", type_="check")


def downgrade() -> None:
    raise RuntimeError("Downgrade is unsupported after historical fund cleanup.")
