"""add bonus points nonnegative

Revision ID: e2b7c4d8f9a1
Revises: 6b17d41e9c2a
Create Date: 2026-07-18 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e2b7c4d8f9a1"
down_revision: str | None = "6b17d41e9c2a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("tournament_results") as batch_op:
        batch_op.create_check_constraint(
            "bonus_points_nonnegative",
            "bonus_points >= 0",
        )


def downgrade() -> None:
    with op.batch_alter_table("tournament_results") as batch_op:
        batch_op.drop_constraint(
            "bonus_points_nonnegative",
            type_="check",
        )
