"""add hall of fame photo slots

Revision ID: f1a2b3c4d5e6
Revises: f0a1b2c3d4e5
Create Date: 2026-08-16 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: str | None = "f0a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("season_hall_of_fame") as batch_op:
        batch_op.add_column(sa.Column("champion_photo_file_id", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("champion_photo_file_unique_id", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("knockout_photo_file_id", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("knockout_photo_file_unique_id", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("season_hall_of_fame") as batch_op:
        batch_op.drop_column("knockout_photo_file_unique_id")
        batch_op.drop_column("knockout_photo_file_id")
        batch_op.drop_column("champion_photo_file_unique_id")
        batch_op.drop_column("champion_photo_file_id")
