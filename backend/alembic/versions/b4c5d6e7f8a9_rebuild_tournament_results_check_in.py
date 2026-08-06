"""rebuild tournament results check-in model

Revision ID: b4c5d6e7f8a9
Revises: a2b3c4d5e6f7
Create Date: 2026-07-31 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b4c5d6e7f8a9"
down_revision: str | None = "a2b3c4d5e6f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tournament_results_rebuilt",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tournament_id", sa.Integer(), nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("checked_in_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("checked_in_by_user_id", sa.Integer(), nullable=True),
        sa.Column("place", sa.Integer(), nullable=True),
        sa.Column("knockouts_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("big_knockouts_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tournament_points", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("knockout_points", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("bonus_points", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "place IS NULL OR place > 0",
            name=op.f("ck_tournament_results_place_positive"),
        ),
        sa.CheckConstraint(
            "knockouts_count >= 0",
            name=op.f("ck_tournament_results_knockouts_count_nonnegative"),
        ),
        sa.CheckConstraint(
            "big_knockouts_count >= 0",
            name=op.f("ck_tournament_results_big_knockouts_count_nonnegative"),
        ),
        sa.CheckConstraint(
            "tournament_points >= 0",
            name=op.f("ck_tournament_results_tournament_points_nonnegative"),
        ),
        sa.CheckConstraint(
            "knockout_points >= 0",
            name=op.f("ck_tournament_results_knockout_points_nonnegative"),
        ),
        sa.CheckConstraint(
            "bonus_points >= 0",
            name=op.f("ck_tournament_results_bonus_points_nonnegative"),
        ),
        sa.ForeignKeyConstraint(
            ["checked_in_by_user_id"],
            ["users.id"],
            name=op.f("fk_tournament_results_checked_in_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["users.id"],
            name=op.f("fk_tournament_results_player_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tournament_id"],
            ["tournaments.id"],
            name=op.f("fk_tournament_results_tournament_id_tournaments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tournament_results")),
        sa.UniqueConstraint(
            "tournament_id",
            "player_id",
            name="uq_tournament_results_tournament_player",
        ),
    )

    op.execute(
        sa.text(
            """
            INSERT INTO tournament_results_rebuilt (
                id,
                tournament_id,
                player_id,
                source,
                checked_in_at,
                checked_in_by_user_id,
                place,
                knockouts_count,
                big_knockouts_count,
                tournament_points,
                knockout_points,
                bonus_points,
                created_at,
                updated_at
            )
            SELECT
                id,
                tournament_id,
                player_id,
                'walk_in_existing',
                updated_at,
                NULL,
                place,
                knockouts_count,
                big_knockouts_count,
                tournament_points,
                knockout_points,
                bonus_points,
                created_at,
                updated_at
            FROM tournament_results
            """
        )
    )

    op.execute(
        sa.text(
            """
            INSERT INTO tournament_results_rebuilt (
                tournament_id,
                player_id,
                source,
                checked_in_at,
                checked_in_by_user_id,
                place,
                knockouts_count,
                big_knockouts_count,
                tournament_points,
                knockout_points,
                bonus_points,
                created_at,
                updated_at
            )
            SELECT
                participant.tournament_id,
                participant.user_id,
                CASE participant.source
                    WHEN 'pre_registered' THEN 'registered'
                    WHEN 'admin_created' THEN 'walk_in_new'
                    ELSE 'walk_in_existing'
                END,
                participant.checked_in_at,
                participant.checked_in_by_user_id,
                draft.place,
                COALESCE(draft.knockouts_count, 0),
                COALESCE(draft.big_knockouts_count, 0),
                0,
                0,
                COALESCE(draft.bonus_points, 0),
                participant.created_at,
                participant.updated_at
            FROM tournament_participants AS participant
            LEFT JOIN tournament_result_drafts AS draft
                ON draft.tournament_id = participant.tournament_id
                AND draft.player_id = participant.user_id
            WHERE NOT EXISTS (
                SELECT 1
                FROM tournament_results AS existing
                WHERE existing.tournament_id = participant.tournament_id
                  AND existing.player_id = participant.user_id
            )
            """
        )
    )

    op.drop_table("tournament_result_drafts")
    op.drop_table("tournament_participants")
    op.drop_table("tournament_results")
    op.rename_table("tournament_results_rebuilt", "tournament_results")
    op.create_index(
        op.f("ix_tournament_results_checked_in_by_user_id"),
        "tournament_results",
        ["checked_in_by_user_id"],
    )
    op.create_index(op.f("ix_tournament_results_player_id"), "tournament_results", ["player_id"])
    op.create_index(op.f("ix_tournament_results_source"), "tournament_results", ["source"])
    op.create_index(
        op.f("ix_tournament_results_tournament_id"),
        "tournament_results",
        ["tournament_id"],
    )


def downgrade() -> None:
    raise RuntimeError(
        "Downgrade from the rebuilt tournament result/check-in model is intentionally "
        "unsupported because the old participant/draft contour no longer exists in "
        "runtime code."
    )
