"""add player rewards

Revision ID: f4b5c6d7e8f9
Revises: f3a4b5c6d7e8
Create Date: 2026-08-23 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f4b5c6d7e8f9"
down_revision: str | None = "f3a4b5c6d7e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "player_rewards",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.Column("reward_type", sa.String(length=32), nullable=False),
        sa.Column("chips_amount", sa.Integer(), nullable=False),
        sa.Column("source_tournament_id", sa.Integer(), nullable=False),
        sa.Column("source_place", sa.Integer(), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_through", sa.Date(), nullable=False),
        sa.Column("redeemed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("redeemed_tournament_id", sa.Integer(), nullable=True),
        sa.Column("redeemed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("redeemed_tournament_day", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["redeemed_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["redeemed_tournament_id"],
            ["tournaments.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_tournament_id"],
            ["tournaments.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_tournament_id",
            "player_id",
            "reward_type",
            name="uq_player_rewards_source_player_type",
        ),
        sa.UniqueConstraint(
            "player_id",
            "redeemed_tournament_day",
            name="uq_player_rewards_player_redeemed_day",
        ),
        sa.CheckConstraint(
            "reward_type IN ('prize_stack_bonus')",
            name="ck_player_rewards_type",
        ),
        sa.CheckConstraint(
            "chips_amount > 0",
            name="ck_player_rewards_chips_positive",
        ),
        sa.CheckConstraint(
            "source_place >= 1 AND source_place <= 3",
            name="ck_player_rewards_source_place",
        ),
        sa.CheckConstraint(
            "(redeemed_at IS NULL AND redeemed_tournament_id IS NULL "
            "AND redeemed_by_user_id IS NULL AND redeemed_tournament_day IS NULL) "
            "OR (redeemed_at IS NOT NULL AND redeemed_tournament_id IS NOT NULL "
            "AND redeemed_by_user_id IS NOT NULL AND redeemed_tournament_day IS NOT NULL)",
            name="ck_player_rewards_redemption_state",
        ),
    )
    op.create_index(
        "ix_player_rewards_player_id",
        "player_rewards",
        ["player_id"],
    )
    op.create_index(
        "ix_player_rewards_redeemed_by_user_id",
        "player_rewards",
        ["redeemed_by_user_id"],
    )
    op.create_index(
        "ix_player_rewards_redeemed_tournament_day",
        "player_rewards",
        ["redeemed_tournament_day"],
    )
    op.create_index(
        "ix_player_rewards_redeemed_tournament_id",
        "player_rewards",
        ["redeemed_tournament_id"],
    )
    op.create_index(
        "ix_player_rewards_reward_type",
        "player_rewards",
        ["reward_type"],
    )
    op.create_index(
        "ix_player_rewards_source_tournament_id",
        "player_rewards",
        ["source_tournament_id"],
    )
    op.create_index(
        "ix_player_rewards_valid_through",
        "player_rewards",
        ["valid_through"],
    )


def downgrade() -> None:
    op.drop_index("ix_player_rewards_valid_through", table_name="player_rewards")
    op.drop_index("ix_player_rewards_source_tournament_id", table_name="player_rewards")
    op.drop_index("ix_player_rewards_reward_type", table_name="player_rewards")
    op.drop_index("ix_player_rewards_redeemed_tournament_id", table_name="player_rewards")
    op.drop_index("ix_player_rewards_redeemed_tournament_day", table_name="player_rewards")
    op.drop_index("ix_player_rewards_redeemed_by_user_id", table_name="player_rewards")
    op.drop_index("ix_player_rewards_player_id", table_name="player_rewards")
    op.drop_table("player_rewards")
