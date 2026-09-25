"""Add achievement presentation types.

Revision ID: d4e5f6a7b8c9
Revises: ce3f4a5b6c7d
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: str | None = "ce3f4a5b6c7d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACHIEVEMENT_TYPES = (
    ("rating_winner", "Победитель рейтингового сезона", "💍"),
    ("ko_rating_winner", "Лучший нокаутер сезона", "💥"),
    ("grand_season", "Победитель Grand Season", "🏆"),
    ("grand_month", "Победитель Grand Month", "🏅"),
    ("grand_knockout", "Победитель Grand Knockout", "🥊"),
)


def upgrade() -> None:
    op.create_table(
        "achievement_types",
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=128), nullable=False),
        sa.Column("emoji", sa.String(length=16), nullable=False),
        sa.Column("custom_emoji_id", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("kind"),
    )
    table = sa.table(
        "achievement_types",
        sa.column("kind", sa.String),
        sa.column("title", sa.String),
        sa.column("emoji", sa.String),
        sa.column("custom_emoji_id", sa.String),
    )
    op.bulk_insert(
        table,
        [
            {"kind": kind, "title": title, "emoji": emoji, "custom_emoji_id": None}
            for kind, title, emoji in ACHIEVEMENT_TYPES
        ],
    )


def downgrade() -> None:
    op.drop_table("achievement_types")
