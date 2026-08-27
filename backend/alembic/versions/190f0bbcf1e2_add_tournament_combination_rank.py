"""add tournament combination rank

Revision ID: 190f0bbcf1e2
Revises: f6d7e8f9a0b1
Create Date: 2026-08-26 23:42:39.679992
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "190f0bbcf1e2"
down_revision: str | None = "f6d7e8f9a0b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("tournament_combinations")}
    with op.batch_alter_table("tournament_combinations") as batch_op:
        if "rank" not in columns:
            batch_op.add_column(sa.Column("rank", sa.String(length=2), nullable=True))
        batch_op.create_check_constraint(
            "ck_tournament_combinations_rank",
            """
            rank IS NULL
            OR (
                combination_type = 'four_of_a_kind'
                AND rank IN ('2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A')
            )
            """,
        )


def downgrade() -> None:
    with op.batch_alter_table("tournament_combinations") as batch_op:
        batch_op.drop_constraint(
            "ck_tournament_combinations_rank",
            type_="check",
        )
        batch_op.drop_column("rank")
