"""add registration matches

Revision ID: 7f3a2d8b9c1e
Revises: d1fb9d1f0c4b
Create Date: 2026-07-13 00:00:00.000000
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "7f3a2d8b9c1e"
down_revision: str | None = "d1fb9d1f0c4b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("players", recreate="always") as batch_op:
        batch_op.drop_constraint("uq_players_full_name", type_="unique")
        batch_op.drop_constraint("uq_players_nickname", type_="unique")
        batch_op.add_column(sa.Column("full_name_normalized", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("nickname_normalized", sa.String(length=100), nullable=True))
        batch_op.create_index(
            batch_op.f("ix_players_full_name_normalized"),
            ["full_name_normalized"],
        )
        batch_op.create_index(
            batch_op.f("ix_players_nickname_normalized"),
            ["nickname_normalized"],
        )

    _populate_normalized_identity()

    op.create_table(
        "registration_matches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pending_player_id", sa.Integer(), nullable=False),
        sa.Column("historical_player_id", sa.Integer(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "candidate",
                "accepted",
                "ignored",
                name="registration_match_status",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "pending_player_id != historical_player_id",
            name=op.f("ck_registration_matches_different_players"),
        ),
        sa.CheckConstraint(
            "score >= 0 AND score <= 100",
            name=op.f("ck_registration_matches_score_range"),
        ),
        sa.ForeignKeyConstraint(
            ["historical_player_id"],
            ["players.id"],
            name=op.f("fk_registration_matches_historical_player_id_players"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["pending_player_id"],
            ["players.id"],
            name=op.f("fk_registration_matches_pending_player_id_players"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_registration_matches")),
        sa.UniqueConstraint(
            "pending_player_id",
            "historical_player_id",
            name="uq_registration_matches_pending_historical",
        ),
    )
    op.create_index(
        op.f("ix_registration_matches_historical_player_id"),
        "registration_matches",
        ["historical_player_id"],
    )
    op.create_index(
        op.f("ix_registration_matches_pending_player_id"),
        "registration_matches",
        ["pending_player_id"],
    )
    op.create_index(
        op.f("ix_registration_matches_status"),
        "registration_matches",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_registration_matches_status"), table_name="registration_matches")
    op.drop_index(
        op.f("ix_registration_matches_pending_player_id"),
        table_name="registration_matches",
    )
    op.drop_index(
        op.f("ix_registration_matches_historical_player_id"),
        table_name="registration_matches",
    )
    op.drop_table("registration_matches")

    with op.batch_alter_table("players", recreate="always") as batch_op:
        batch_op.drop_index(batch_op.f("ix_players_nickname_normalized"))
        batch_op.drop_index(batch_op.f("ix_players_full_name_normalized"))
        batch_op.drop_column("nickname_normalized")
        batch_op.drop_column("full_name_normalized")
        batch_op.create_unique_constraint("uq_players_nickname", ["nickname"])
        batch_op.create_unique_constraint("uq_players_full_name", ["full_name"])


def _populate_normalized_identity() -> None:
    connection = op.get_bind()
    players = connection.execute(
        sa.text("SELECT id, full_name, nickname FROM players")
    ).mappings()
    for player in players:
        connection.execute(
            sa.text(
                """
                UPDATE players
                SET full_name_normalized = :full_name_normalized,
                    nickname_normalized = :nickname_normalized
                WHERE id = :id
                """
            ),
            {
                "id": player["id"],
                "full_name_normalized": _normalize_full_name(player["full_name"]),
                "nickname_normalized": _normalize_nickname(player["nickname"]),
            },
        )


def _normalize_full_name(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.casefold().replace("ё", "е")
    normalized = re.sub(r"[^0-9a-zа-я]+", " ", normalized)
    normalized = " ".join(normalized.split())
    return normalized or None


def _normalize_nickname(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.casefold().replace("ё", "е").strip()
    normalized = normalized.removeprefix("@")
    normalized = re.sub(r"[\s._-]+", "", normalized)
    normalized = re.sub(r"[^0-9a-zа-я]+", "", normalized)
    return normalized or None
