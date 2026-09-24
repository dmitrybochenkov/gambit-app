"""add Hall of Fame achievement occurrences

Revision ID: ac1d2e3f4a5b
Revises: 9b0c1d2e3f4a
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "ac1d2e3f4a5b"
down_revision: str | None = "9b0c1d2e3f4a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hall_of_fame_achievements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("season_id", sa.Integer(), nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("awarded_at", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('rating_winner', 'ko_rating_winner', 'grand_season', "
            "'grand_month', 'grand_knockout')",
            name="hall_of_fame_achievements_kind_values",
        ),
        sa.ForeignKeyConstraint(["player_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["season_id"], ["seasons.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("season_id", "player_id", "kind", "awarded_at"):
        op.create_index(
            f"ix_hall_of_fame_achievements_{column}",
            "hall_of_fame_achievements",
            [column],
        )
    op.execute(
        sa.text(
            """
            INSERT INTO hall_of_fame_achievements
                (season_id, player_id, kind, awarded_at, created_at, updated_at)
            SELECT hof.season_id, hof.champion_player_id, 'rating_winner', season.ends_at,
                   hof.created_at, hof.updated_at
            FROM season_hall_of_fame AS hof
            JOIN seasons AS season ON season.id = hof.season_id
            WHERE hof.champion_player_id IS NOT NULL AND season.ends_at IS NOT NULL
            UNION ALL
            SELECT hof.season_id, hof.knockout_player_id, 'ko_rating_winner', season.ends_at,
                   hof.created_at, hof.updated_at
            FROM season_hall_of_fame AS hof
            JOIN seasons AS season ON season.id = hof.season_id
            WHERE hof.knockout_player_id IS NOT NULL AND season.ends_at IS NOT NULL
            """
        )
    )


def downgrade() -> None:
    connection = op.get_bind()
    unsupported_count = connection.execute(
        sa.text(
            """
            SELECT COUNT(*)
            FROM hall_of_fame_achievements AS achievement
            WHERE kind NOT IN ('rating_winner', 'ko_rating_winner')
               OR NOT EXISTS (
                    SELECT 1
                    FROM season_hall_of_fame AS legacy
                    WHERE legacy.season_id = achievement.season_id
               )
            """
        )
    ).scalar_one()
    duplicate_count = connection.execute(
        sa.text(
            """
            SELECT COUNT(*)
            FROM (
                SELECT season_id, kind
                FROM hall_of_fame_achievements
                GROUP BY season_id, kind
                HAVING COUNT(*) > 1
            ) AS duplicates
            """
        )
    ).scalar_one()
    unrepresented_legacy_count = connection.execute(
        sa.text(
            """
            SELECT COUNT(*)
            FROM season_hall_of_fame AS legacy
            WHERE (
                    legacy.champion_player_id IS NOT NULL
                    AND NOT EXISTS (
                        SELECT 1
                        FROM hall_of_fame_achievements AS achievement
                        WHERE achievement.season_id = legacy.season_id
                          AND achievement.kind = 'rating_winner'
                    )
                )
               OR (
                    legacy.knockout_player_id IS NOT NULL
                    AND NOT EXISTS (
                        SELECT 1
                        FROM hall_of_fame_achievements AS achievement
                        WHERE achievement.season_id = legacy.season_id
                          AND achievement.kind = 'ko_rating_winner'
                    )
                )
            """
        )
    ).scalar_one()
    if unsupported_count or duplicate_count or unrepresented_legacy_count:
        raise RuntimeError(
            "Cannot downgrade: Hall of Fame occurrences cannot be represented by legacy slots."
        )

    connection.execute(
        sa.text(
            """
            UPDATE season_hall_of_fame
            SET champion_player_id = (
                    SELECT player_id
                    FROM hall_of_fame_achievements
                    WHERE season_id = season_hall_of_fame.season_id
                      AND kind = 'rating_winner'
                ),
                knockout_player_id = (
                    SELECT player_id
                    FROM hall_of_fame_achievements
                    WHERE season_id = season_hall_of_fame.season_id
                      AND kind = 'ko_rating_winner'
                )
            """
        )
    )
    for column in ("awarded_at", "kind", "player_id", "season_id"):
        op.drop_index(
            f"ix_hall_of_fame_achievements_{column}",
            table_name="hall_of_fame_achievements",
        )
    op.drop_table("hall_of_fame_achievements")
