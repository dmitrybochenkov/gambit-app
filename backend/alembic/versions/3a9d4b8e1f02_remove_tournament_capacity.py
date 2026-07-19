"""remove tournament capacity

Revision ID: 3a9d4b8e1f02
Revises: f4a1c2d3e5b6
Create Date: 2026-07-19 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "3a9d4b8e1f02"
down_revision: str | None = "f4a1c2d3e5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("tournaments") as batch_op:
        batch_op.drop_constraint(
            "capacity_positive",
            type_="check",
        )
        batch_op.drop_column("capacity")


def downgrade() -> None:
    with op.batch_alter_table("tournaments") as batch_op:
        batch_op.add_column(
            sa.Column(
                "capacity",
                sa.Integer(),
                nullable=False,
                server_default="30",
            )
        )
        batch_op.create_check_constraint(
            "ck_tournaments_capacity_positive",
            "capacity > 0",
        )
