"""enforce integer bonus points

Revision ID: c0d1e2f3a4b5
Revises: b0c1d2e3f4a5
Create Date: 2026-08-07 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c0d1e2f3a4b5"
down_revision: str | None = "b0c1d2e3f4a5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("tournament_results") as batch_op:
        batch_op.drop_constraint("bonus_points_nonnegative", type_="check")
        batch_op.create_check_constraint(
            "bonus_points_nonnegative",
            "bonus_points >= 0 AND bonus_points = CAST(bonus_points AS INTEGER)",
        )


def downgrade() -> None:
    raise RuntimeError("Downgrade is unsupported after enforcing integer bonus points.")
