"""add hall of fame photos

Revision ID: bd2e3f4a5b6c
Revises: ac1d2e3f4a5b
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "bd2e3f4a5b6c"
down_revision: str | None = "ac1d2e3f4a5b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hall_of_fame_photos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("season_id", sa.Integer(), nullable=False),
        sa.Column("telegram_file_id", sa.String(length=255), nullable=False),
        sa.Column("telegram_file_unique_id", sa.String(length=255), nullable=False),
        sa.Column("uploaded_by_user_id", sa.Integer(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("position >= 0", name="ck_hall_of_fame_photos_position_nonnegative"),
        sa.ForeignKeyConstraint(["season_id"], ["seasons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "season_id",
            "telegram_file_unique_id",
            name="uq_hall_of_fame_photos_season_unique_file",
        ),
    )
    op.create_index("ix_hall_of_fame_photos_season_id", "hall_of_fame_photos", ["season_id"])
    op.create_index(
        "ix_hall_of_fame_photos_uploaded_by_user_id",
        "hall_of_fame_photos",
        ["uploaded_by_user_id"],
    )
    op.execute(
        sa.text(
            """
            INSERT INTO hall_of_fame_photos
                (season_id, telegram_file_id, telegram_file_unique_id,
                 uploaded_by_user_id, position, created_at)
            SELECT season_id, champion_photo_file_id, champion_photo_file_unique_id,
                   updated_by_user_id, 0, created_at
            FROM season_hall_of_fame
            WHERE champion_photo_file_id IS NOT NULL
              AND champion_photo_file_unique_id IS NOT NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT OR IGNORE INTO hall_of_fame_photos
                (season_id, telegram_file_id, telegram_file_unique_id,
                 uploaded_by_user_id, position, created_at)
            SELECT season_id, knockout_photo_file_id, knockout_photo_file_unique_id,
                   updated_by_user_id, 1, created_at
            FROM season_hall_of_fame
            WHERE knockout_photo_file_id IS NOT NULL
              AND knockout_photo_file_unique_id IS NOT NULL
            """
        )
    )


def downgrade() -> None:
    connection = op.get_bind()
    excessive = connection.execute(
        sa.text(
            "SELECT season_id FROM hall_of_fame_photos "
            "GROUP BY season_id HAVING COUNT(*) > 2 LIMIT 1"
        )
    ).first()
    if excessive is not None:
        raise RuntimeError(
            "Cannot downgrade Hall of Fame photos: a season has more than two photos"
        )

    op.execute(
        sa.text(
            """
            UPDATE season_hall_of_fame
            SET champion_photo_file_id = NULL,
                champion_photo_file_unique_id = NULL,
                knockout_photo_file_id = NULL,
                knockout_photo_file_unique_id = NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE season_hall_of_fame
            SET champion_photo_file_id = (
                    SELECT telegram_file_id FROM hall_of_fame_photos p
                    WHERE p.season_id = season_hall_of_fame.season_id
                    ORDER BY p.position, p.id LIMIT 1
                ),
                champion_photo_file_unique_id = (
                    SELECT telegram_file_unique_id FROM hall_of_fame_photos p
                    WHERE p.season_id = season_hall_of_fame.season_id
                    ORDER BY p.position, p.id LIMIT 1
                ),
                knockout_photo_file_id = (
                    SELECT telegram_file_id FROM hall_of_fame_photos p
                    WHERE p.season_id = season_hall_of_fame.season_id
                    ORDER BY p.position, p.id LIMIT 1 OFFSET 1
                ),
                knockout_photo_file_unique_id = (
                    SELECT telegram_file_unique_id FROM hall_of_fame_photos p
                    WHERE p.season_id = season_hall_of_fame.season_id
                    ORDER BY p.position, p.id LIMIT 1 OFFSET 1
                )
            """
        )
    )
    op.drop_index("ix_hall_of_fame_photos_uploaded_by_user_id", table_name="hall_of_fame_photos")
    op.drop_index("ix_hall_of_fame_photos_season_id", table_name="hall_of_fame_photos")
    op.drop_table("hall_of_fame_photos")
