"""add season hall of fame

Revision ID: e3f4a5b6c7d8
Revises: e2f3a4b5c6d7
Create Date: 2026-08-09 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e3f4a5b6c7d8"
down_revision: str | None = "e2f3a4b5c6d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "season_hall_of_fame",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("season_id", sa.Integer(), nullable=False),
        sa.Column("champion_player_id", sa.Integer(), nullable=True),
        sa.Column("knockout_player_id", sa.Integer(), nullable=True),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["champion_player_id"],
            ["users.id"],
            name=op.f("fk_season_hall_of_fame_champion_player_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["knockout_player_id"],
            ["users.id"],
            name=op.f("fk_season_hall_of_fame_knockout_player_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["season_id"],
            ["seasons.id"],
            name=op.f("fk_season_hall_of_fame_season_id_seasons"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["users.id"],
            name=op.f("fk_season_hall_of_fame_updated_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_season_hall_of_fame")),
        sa.UniqueConstraint("season_id", name="uq_season_hall_of_fame_season_id"),
    )
    op.create_index(
        op.f("ix_season_hall_of_fame_champion_player_id"),
        "season_hall_of_fame",
        ["champion_player_id"],
    )
    op.create_index(
        op.f("ix_season_hall_of_fame_knockout_player_id"),
        "season_hall_of_fame",
        ["knockout_player_id"],
    )
    op.create_index(
        op.f("ix_season_hall_of_fame_updated_by_user_id"),
        "season_hall_of_fame",
        ["updated_by_user_id"],
    )
    op.execute(
        sa.text(
            """
            UPDATE tournament_type_rules
            SET knockout_mode = 'none',
                supports_bonus_points = 1
            WHERE tournament_type_id = (
                SELECT id FROM tournament_types WHERE code = 'mystery_bounty'
            )
            """
        )
    )


def downgrade() -> None:
    raise RuntimeError("Downgrade is unsupported after adding manually curated Hall of Fame.")
