"""allow duplicate historical result places

Revision ID: e8f9a0b1c2d3
Revises: e6f7a8b9c0d1
Create Date: 2026-08-10 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e8f9a0b1c2d3"
down_revision: str | None = "e6f7a8b9c0d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index(
        "uq_tournament_results_tournament_place",
        table_name="tournament_results",
    )


def downgrade() -> None:
    raise RuntimeError(
        "Downgrade is unsupported because historical results may contain tied places."
    )
