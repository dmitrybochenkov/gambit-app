"""add reward expiration reminders

Revision ID: f5c6d7e8f9a0
Revises: f4b5c6d7e8f9
Create Date: 2026-08-23 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f5c6d7e8f9a0"
down_revision: str | None = "f4b5c6d7e8f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "player_rewards",
        sa.Column("expiration_reminder_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_player_rewards_expiration_reminder_sent_at",
        "player_rewards",
        ["expiration_reminder_sent_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_player_rewards_expiration_reminder_sent_at",
        table_name="player_rewards",
    )
    op.drop_column("player_rewards", "expiration_reminder_sent_at")
