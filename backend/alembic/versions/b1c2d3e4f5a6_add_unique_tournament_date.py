"""add unique tournament date

Revision ID: b1c2d3e4f5a6
Revises: a8d4e6f1c2b3
Create Date: 2026-07-27 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b1c2d3e4f5a6"
down_revision: str | None = "a8d4e6f1c2b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("tournaments") as batch_op:
        batch_op.create_unique_constraint(
            "uq_tournaments_date",
            ["date"],
        )


def downgrade() -> None:
    with op.batch_alter_table("tournaments") as batch_op:
        batch_op.drop_constraint(
            "uq_tournaments_date",
            type_="unique",
        )
