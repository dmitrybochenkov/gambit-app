"""finalize Hall of Fame occurrence model

Revision ID: ce3f4a5b6c7d
Revises: bd2e3f4a5b6c
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "ce3f4a5b6c7d"
down_revision: str | None = "bd2e3f4a5b6c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SINGLETON_KINDS = "'rating_winner', 'ko_rating_winner', 'grand_season'"


def upgrade() -> None:
    op.create_index(
        "uq_hall_of_fame_achievements_singleton_kind",
        "hall_of_fame_achievements",
        ["season_id", "kind"],
        unique=True,
        sqlite_where=sa.text(f"kind IN ({_SINGLETON_KINDS})"),
        postgresql_where=sa.text(f"kind IN ({_SINGLETON_KINDS})"),
    )
    op.drop_table("season_hall_of_fame")


def downgrade() -> None:
    connection = op.get_bind()
    unsupported = connection.execute(
        sa.text(
            "SELECT 1 FROM hall_of_fame_achievements "
            "WHERE kind IN ('grand_season', 'grand_month', 'grand_knockout') LIMIT 1"
        )
    ).first()
    if unsupported is not None:
        raise RuntimeError(
            "Cannot downgrade Hall of Fame: grand achievements cannot be represented"
        )
    excessive_photos = connection.execute(
        sa.text(
            "SELECT season_id FROM hall_of_fame_photos "
            "GROUP BY season_id HAVING COUNT(*) > 2 LIMIT 1"
        )
    ).first()
    if excessive_photos is not None:
        raise RuntimeError("Cannot downgrade Hall of Fame: a season has more than two photos")
    updater_id = connection.execute(
        sa.text(
            "SELECT id FROM users WHERE role = 'superadmin' AND status = 'active' "
            "ORDER BY id LIMIT 1"
        )
    ).scalar_one_or_none()
    has_content = connection.execute(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM hall_of_fame_achievements) "
            "OR EXISTS(SELECT 1 FROM hall_of_fame_photos)"
        )
    ).scalar_one()
    if has_content and updater_id is None:
        raise RuntimeError("Cannot downgrade Hall of Fame: no active superadmin for legacy rows")

    op.create_table(
        "season_hall_of_fame",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("season_id", sa.Integer(), nullable=False),
        sa.Column("champion_player_id", sa.Integer(), nullable=True),
        sa.Column("knockout_player_id", sa.Integer(), nullable=True),
        sa.Column("champion_photo_file_id", sa.String(), nullable=True),
        sa.Column("champion_photo_file_unique_id", sa.String(), nullable=True),
        sa.Column("knockout_photo_file_id", sa.String(), nullable=True),
        sa.Column("knockout_photo_file_unique_id", sa.String(), nullable=True),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["champion_player_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["knockout_player_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["season_id"], ["seasons.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("season_id", name="uq_season_hall_of_fame_season_id"),
    )
    op.create_index(
        "ix_season_hall_of_fame_champion_player_id",
        "season_hall_of_fame",
        ["champion_player_id"],
    )
    op.create_index(
        "ix_season_hall_of_fame_knockout_player_id",
        "season_hall_of_fame",
        ["knockout_player_id"],
    )
    op.create_index(
        "ix_season_hall_of_fame_updated_by_user_id",
        "season_hall_of_fame",
        ["updated_by_user_id"],
    )
    if has_content:
        connection.execute(
            sa.text(
                """
                INSERT INTO season_hall_of_fame (
                    season_id, champion_player_id, knockout_player_id,
                    champion_photo_file_id, champion_photo_file_unique_id,
                    knockout_photo_file_id, knockout_photo_file_unique_id,
                    updated_by_user_id, created_at, updated_at
                )
                SELECT s.id,
                    (SELECT player_id FROM hall_of_fame_achievements a
                     WHERE a.season_id=s.id AND a.kind='rating_winner' LIMIT 1),
                    (SELECT player_id FROM hall_of_fame_achievements a
                     WHERE a.season_id=s.id AND a.kind='ko_rating_winner' LIMIT 1),
                    (SELECT telegram_file_id FROM hall_of_fame_photos p
                     WHERE p.season_id=s.id ORDER BY p.position,p.id LIMIT 1),
                    (SELECT telegram_file_unique_id FROM hall_of_fame_photos p
                     WHERE p.season_id=s.id ORDER BY p.position,p.id LIMIT 1),
                    (SELECT telegram_file_id FROM hall_of_fame_photos p
                     WHERE p.season_id=s.id ORDER BY p.position,p.id LIMIT 1 OFFSET 1),
                    (SELECT telegram_file_unique_id FROM hall_of_fame_photos p
                     WHERE p.season_id=s.id ORDER BY p.position,p.id LIMIT 1 OFFSET 1),
                    :updater_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                FROM seasons s
                WHERE EXISTS (SELECT 1 FROM hall_of_fame_achievements a WHERE a.season_id=s.id)
                   OR EXISTS (SELECT 1 FROM hall_of_fame_photos p WHERE p.season_id=s.id)
                """
            ),
            {"updater_id": updater_id},
        )
    op.drop_index(
        "uq_hall_of_fame_achievements_singleton_kind",
        table_name="hall_of_fame_achievements",
    )
