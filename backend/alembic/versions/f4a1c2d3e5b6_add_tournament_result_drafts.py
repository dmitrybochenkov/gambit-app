"""add tournament result drafts

Revision ID: f4a1c2d3e5b6
Revises: e2b7c4d8f9a1
Create Date: 2026-07-18 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f4a1c2d3e5b6"
down_revision: str | None = "e2b7c4d8f9a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tournament_result_drafts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tournament_id", sa.Integer(), nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.Column("place", sa.Integer(), nullable=True),
        sa.Column("knockouts_count", sa.Integer(), nullable=False),
        sa.Column("boss_knockouts_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "boss_knockouts_count >= 0",
            name=op.f("ck_tournament_result_drafts_boss_knockouts_count_nonnegative"),
        ),
        sa.CheckConstraint(
            "knockouts_count >= 0",
            name=op.f("ck_tournament_result_drafts_knockouts_count_nonnegative"),
        ),
        sa.CheckConstraint(
            "place IS NULL OR place > 0",
            name=op.f("ck_tournament_result_drafts_place_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["players.id"],
            name=op.f("fk_tournament_result_drafts_player_id_players"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tournament_id"],
            ["tournaments.id"],
            name=op.f("fk_tournament_result_drafts_tournament_id_tournaments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tournament_result_drafts")),
        sa.UniqueConstraint(
            "tournament_id",
            "player_id",
            name="uq_tournament_result_drafts_tournament_player",
        ),
    )
    op.create_index(
        op.f("ix_tournament_result_drafts_player_id"),
        "tournament_result_drafts",
        ["player_id"],
    )
    op.create_index(
        op.f("ix_tournament_result_drafts_tournament_id"),
        "tournament_result_drafts",
        ["tournament_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_tournament_result_drafts_tournament_id"),
        table_name="tournament_result_drafts",
    )
    op.drop_index(
        op.f("ix_tournament_result_drafts_player_id"),
        table_name="tournament_result_drafts",
    )
    op.drop_table("tournament_result_drafts")
