"""add tournament photos

Revision ID: f0a1b2c3d4e5
Revises: e9f0a1b2c3d4
Create Date: 2026-08-14 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f0a1b2c3d4e5"
down_revision: str | None = "e9f0a1b2c3d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tournament_photos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tournament_id", sa.Integer(), nullable=False),
        sa.Column("telegram_file_id", sa.String(length=255), nullable=False),
        sa.Column("telegram_file_unique_id", sa.String(length=255), nullable=False),
        sa.Column("uploaded_by_user_id", sa.Integer(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tournament_id"],
            ["tournaments.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "tournament_id",
            "telegram_file_unique_id",
            name="uq_tournament_photos_tournament_unique_file",
        ),
        sa.CheckConstraint(
            "position >= 0",
            name="ck_tournament_photos_position_nonnegative",
        ),
    )
    op.create_index(
        op.f("ix_tournament_photos_tournament_id"),
        "tournament_photos",
        ["tournament_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tournament_photos_uploaded_by_user_id"),
        "tournament_photos",
        ["uploaded_by_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_tournament_photos_uploaded_by_user_id"), table_name="tournament_photos")
    op.drop_index(op.f("ix_tournament_photos_tournament_id"), table_name="tournament_photos")
    op.drop_table("tournament_photos")
