"""strict tournament schema after pre-production reset

Revision ID: f9a0b1c2d3e4
Revises: f8a9b0c1d2e3
Create Date: 2026-08-06 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f9a0b1c2d3e4"
down_revision: str | None = "f8a9b0c1d2e3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("tournament_results") as batch_op:
        batch_op.drop_constraint("place_positive", type_="check")
        batch_op.drop_constraint("bonus_points_nonnegative", type_="check")
        batch_op.alter_column(
            "bonus_points",
            existing_type=sa.Numeric(precision=12, scale=2),
            type_=sa.Integer(),
            existing_nullable=False,
            server_default="0",
        )
        batch_op.create_check_constraint(
            "source",
            "source IN ('registered', 'walk_in_existing', 'walk_in_new')",
        )
        batch_op.create_check_constraint(
            "place_range",
            "place IS NULL OR (place >= 1 AND place <= 5)",
        )
        batch_op.create_check_constraint(
            "bonus_points_nonnegative",
            "bonus_points >= 0",
        )

    op.create_index(
        "uq_tournament_results_tournament_place",
        "tournament_results",
        ["tournament_id", "place"],
        unique=True,
        sqlite_where=sa.text("place IS NOT NULL"),
    )

    with op.batch_alter_table("tournaments") as batch_op:
        batch_op.drop_constraint("tournament_fund_nonnegative", type_="check")
        batch_op.drop_constraint("closed_has_tournament_fund", type_="check")
        batch_op.alter_column(
            "tournament_fund",
            existing_type=sa.Numeric(precision=12, scale=2),
            type_=sa.Integer(),
            existing_nullable=True,
        )
        batch_op.create_check_constraint(
            "tournament_fund",
            "tournament_fund IS NULL OR (tournament_fund > 0 AND tournament_fund % 10 = 0)",
        )
        batch_op.create_check_constraint(
            "tournament_fund_status",
            "(status = 'closed' AND tournament_fund IS NOT NULL) "
            "OR (status != 'closed' AND tournament_fund IS NULL)",
        )


def downgrade() -> None:
    raise RuntimeError(
        "Downgrade is unsupported after strict pre-production tournament schema migration."
    )
