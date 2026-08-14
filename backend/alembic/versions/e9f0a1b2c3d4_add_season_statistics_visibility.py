"""add season statistics visibility flag

Revision ID: e9f0a1b2c3d4
Revises: e8f9a0b1c2d3
Create Date: 2026-08-14 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e9f0a1b2c3d4"
down_revision: str | None = "e8f9a0b1c2d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("seasons") as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_statistics_visible",
                sa.Boolean(),
                server_default=sa.text("1"),
                nullable=False,
            )
        )
    op.execute(
        """
        UPDATE seasons
        SET is_statistics_visible = 0
        WHERE id = (
            SELECT id
            FROM seasons
            ORDER BY starts_at ASC, id ASC
            LIMIT 1
        )
        """
    )


def downgrade() -> None:
    with op.batch_alter_table("seasons") as batch_op:
        batch_op.drop_column("is_statistics_visible")
