"""add combinations and publications

Revision ID: f3a4b5c6d7e8
Revises: f2a3b4c5d6e7
Create Date: 2026-08-22 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f3a4b5c6d7e8"
down_revision: str | None = "f2a3b4c5d6e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tournament_combinations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tournament_id", sa.Integer(), nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.Column("combination_type", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tournament_id"],
            ["tournaments.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tournament_id",
            "player_id",
            "combination_type",
            name="uq_tournament_combinations_tournament_player_type",
        ),
        sa.CheckConstraint(
            "combination_type IN ('four_of_a_kind', 'straight_flush', 'royal_flush')",
            name="ck_tournament_combinations_type",
        ),
    )
    op.create_index(
        "ix_tournament_combinations_combination_type",
        "tournament_combinations",
        ["combination_type"],
    )
    op.create_index(
        "ix_tournament_combinations_player_id",
        "tournament_combinations",
        ["player_id"],
    )
    op.create_index(
        "ix_tournament_combinations_tournament_id",
        "tournament_combinations",
        ["tournament_id"],
    )

    op.create_table(
        "tournament_publications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tournament_id", sa.Integer(), nullable=True),
        sa.Column("publication_type", sa.String(length=16), nullable=False),
        sa.Column("destination_type", sa.String(length=16), nullable=False),
        sa.Column("destination_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("telegram_message_id", sa.Integer(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_by_user_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["published_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tournament_id"],
            ["tournaments.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "publication_type",
            "destination_type",
            "destination_chat_id",
            "content_hash",
            name="uq_tournament_publications_identity",
        ),
        sa.CheckConstraint(
            "publication_type IN ('results', 'schedule')",
            name="ck_tournament_publications_type",
        ),
        sa.CheckConstraint(
            "destination_type IN ('group', 'channel')",
            name="ck_tournament_publications_destination",
        ),
    )
    op.create_index(
        "ix_tournament_publications_destination_type",
        "tournament_publications",
        ["destination_type"],
    )
    op.create_index(
        "ix_tournament_publications_publication_type",
        "tournament_publications",
        ["publication_type"],
    )
    op.create_index(
        "ix_tournament_publications_published_by_user_id",
        "tournament_publications",
        ["published_by_user_id"],
    )
    op.create_index(
        "ix_tournament_publications_tournament_id",
        "tournament_publications",
        ["tournament_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tournament_publications_tournament_id",
        table_name="tournament_publications",
    )
    op.drop_index(
        "ix_tournament_publications_published_by_user_id",
        table_name="tournament_publications",
    )
    op.drop_index(
        "ix_tournament_publications_publication_type",
        table_name="tournament_publications",
    )
    op.drop_index(
        "ix_tournament_publications_destination_type",
        table_name="tournament_publications",
    )
    op.drop_table("tournament_publications")

    op.drop_index(
        "ix_tournament_combinations_tournament_id",
        table_name="tournament_combinations",
    )
    op.drop_index(
        "ix_tournament_combinations_player_id",
        table_name="tournament_combinations",
    )
    op.drop_index(
        "ix_tournament_combinations_combination_type",
        table_name="tournament_combinations",
    )
    op.drop_table("tournament_combinations")
