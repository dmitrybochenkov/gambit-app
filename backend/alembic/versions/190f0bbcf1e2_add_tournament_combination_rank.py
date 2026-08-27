"""add tournament combination rank

Revision ID: 190f0bbcf1e2
Revises: f6d7e8f9a0b1
Create Date: 2026-08-26 23:42:39.679992
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = '190f0bbcf1e2'
down_revision: str | None = 'f6d7e8f9a0b1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tournament_combinations",
        sa.Column("rank", sa.String(length=2), nullable=True),
    )
    op.create_check_constraint(
        "ck_tournament_combinations_rank",
        "tournament_combinations",
        """
        rank IS NULL
        OR (
            combination_type = 'four_of_a_kind'
            AND rank IN ('2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A')
        )
        """,
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_tournament_combinations_rank",
        "tournament_combinations",
        type_="check",
    )
    op.drop_column("tournament_combinations", "rank")