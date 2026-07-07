"""allow missing result places

Revision ID: 2ce4d6b5027c
Revises: a4e9ba37fa36
Create Date: 2026-07-07 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "2ce4d6b5027c"
down_revision: str | None = "a4e9ba37fa36"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("tournament_results") as batch_op:
        batch_op.drop_constraint(
            "uq_tournament_results_tournament_place",
            type_="unique",
        )
        batch_op.drop_constraint(
            "place_positive",
            type_="check",
        )
        batch_op.alter_column(
            "place",
            existing_type=sa.Integer(),
            nullable=True,
        )
        batch_op.create_check_constraint(
            "place_positive",
            "place IS NULL OR place > 0",
        )


def downgrade() -> None:
    op.execute("DELETE FROM tournament_results WHERE place IS NULL")
    with op.batch_alter_table("tournament_results") as batch_op:
        batch_op.drop_constraint(
            "place_positive",
            type_="check",
        )
        batch_op.alter_column(
            "place",
            existing_type=sa.Integer(),
            nullable=False,
        )
        batch_op.create_check_constraint(
            "place_positive",
            "place > 0",
        )
        batch_op.create_unique_constraint(
            "uq_tournament_results_tournament_place",
            ["tournament_id", "place"],
        )
