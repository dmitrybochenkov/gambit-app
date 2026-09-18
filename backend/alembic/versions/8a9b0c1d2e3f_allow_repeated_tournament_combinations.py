"""allow repeated tournament combination occurrences

Revision ID: 8a9b0c1d2e3f
Revises: 7f8a9b0c1d2e
Create Date: 2026-09-18 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "8a9b0c1d2e3f"
down_revision: str | None = "7f8a9b0c1d2e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("tournament_combinations") as batch_op:
        batch_op.drop_constraint(
            "uq_tournament_combinations_tournament_player_type",
            type_="unique",
        )


def downgrade() -> None:
    with op.batch_alter_table("tournament_combinations") as batch_op:
        batch_op.create_unique_constraint(
            "uq_tournament_combinations_tournament_player_type",
            ["tournament_id", "player_id", "combination_type"],
        )
