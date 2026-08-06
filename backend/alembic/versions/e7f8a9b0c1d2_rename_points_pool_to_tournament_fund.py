"""rename points pool to tournament fund

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
Create Date: 2026-08-06 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e7f8a9b0c1d2"
down_revision: str | None = "d6e7f8a9b0c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("tournaments") as batch_op:
        batch_op.drop_constraint("points_pool_nonnegative", type_="check")
        batch_op.drop_constraint("closed_has_points_pool", type_="check")
        batch_op.alter_column(
            "points_pool",
            new_column_name="tournament_fund",
            existing_type=sa.Numeric(precision=12, scale=2),
            nullable=True,
        )
        batch_op.create_check_constraint(
            "tournament_fund_nonnegative",
            "tournament_fund IS NULL OR tournament_fund >= 0",
        )
        batch_op.create_check_constraint(
            "closed_has_tournament_fund",
            "status != 'closed' OR tournament_fund IS NOT NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("tournaments") as batch_op:
        batch_op.drop_constraint("tournament_fund_nonnegative", type_="check")
        batch_op.drop_constraint("closed_has_tournament_fund", type_="check")
        batch_op.alter_column(
            "tournament_fund",
            new_column_name="points_pool",
            existing_type=sa.Numeric(precision=12, scale=2),
            nullable=True,
        )
        batch_op.create_check_constraint(
            "points_pool_nonnegative",
            "points_pool IS NULL OR points_pool >= 0",
        )
        batch_op.create_check_constraint(
            "closed_has_points_pool",
            "status != 'closed' OR points_pool IS NOT NULL",
        )
