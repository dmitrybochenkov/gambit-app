"""Fix canonical achievement type metadata.

Revision ID: f6a7b8c9d0e2
Revises: e5f6a7b8c9d1
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f6a7b8c9d0e2"
down_revision: str | None = "e5f6a7b8c9d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_METADATA = {
    "grand_season": ("Победитель Grand Season", "💍"),
    "rating_winner": ("Победитель Season Rating", "🏆"),
    "ko_rating_winner": ("Победитель KO Season Rating", "💥"),
    "grand_month": ("Победитель Grand Month", "🏅"),
    "grand_knockout": ("Победитель Grand Knockout", "🥊"),
}

PREVIOUS_METADATA = {
    "rating_winner": ("Победитель рейтингового сезона", "💍"),
    "ko_rating_winner": ("Лучший нокаутер сезона", "💥"),
    "grand_season": ("Победитель Grand Season", "🏆"),
    "grand_month": ("Победитель Grand Month", "🏅"),
    "grand_knockout": ("Победитель Grand Knockout", "🥊"),
}


def upgrade() -> None:
    _update_metadata(NEW_METADATA)


def downgrade() -> None:
    _update_metadata(PREVIOUS_METADATA)


def _update_metadata(metadata: dict[str, tuple[str, str]]) -> None:
    connection = op.get_bind()
    statement = sa.text(
        """
        UPDATE achievement_types
        SET title = :title, emoji = :emoji
        WHERE kind = :kind
        """
    )
    for kind, (title, emoji) in metadata.items():
        result = connection.execute(
            statement,
            {"kind": kind, "title": title, "emoji": emoji},
        )
        if result.rowcount != 1:
            raise RuntimeError(f"Expected exactly one achievement type for {kind!r}")
