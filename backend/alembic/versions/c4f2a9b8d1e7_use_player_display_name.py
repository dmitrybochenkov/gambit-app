"""use player display name

Revision ID: c4f2a9b8d1e7
Revises: b8c2e4f6a9d1
Create Date: 2026-07-27 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c4f2a9b8d1e7"
down_revision: str | None = "b8c2e4f6a9d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("players") as batch_op:
        batch_op.add_column(sa.Column("display_name", sa.String(length=255), nullable=True))
        batch_op.add_column(
            sa.Column("display_name_normalized", sa.String(length=255), nullable=True)
        )

    connection = op.get_bind()
    conflict_ids = _player_ids(
        connection,
        """
        SELECT id FROM players
        WHERE full_name IS NOT NULL AND nickname IS NOT NULL
        ORDER BY id
        """,
    )
    if conflict_ids:
        raise RuntimeError(
            "Cannot migrate players with both full_name and nickname set. "
            f"Player ids: {', '.join(map(str, conflict_ids))}."
        )

    empty_ids = _player_ids(
        connection,
        """
        SELECT id FROM players
        WHERE full_name IS NULL AND nickname IS NULL
        ORDER BY id
        """,
    )
    if empty_ids:
        raise RuntimeError(
            "Cannot migrate players without full_name or nickname. "
            f"Player ids: {', '.join(map(str, empty_ids))}."
        )

    players = connection.execute(
        sa.text("SELECT id, COALESCE(full_name, nickname) AS display_name FROM players")
    ).mappings()
    for player in players:
        display_name = player["display_name"]
        connection.execute(
            sa.text(
                """
                UPDATE players
                   SET display_name = :display_name,
                       display_name_normalized = :display_name_normalized
                 WHERE id = :id
                """
            ),
            {
                "id": player["id"],
                "display_name": display_name,
                "display_name_normalized": _normalize_display_name(display_name),
            },
        )

    with op.batch_alter_table("players") as batch_op:
        batch_op.drop_constraint(batch_op.f("ck_players_identity_present"), type_="check")
        batch_op.drop_index(batch_op.f("ix_players_full_name_normalized"))
        batch_op.drop_index(batch_op.f("ix_players_nickname_normalized"))
        batch_op.alter_column(
            "display_name",
            existing_type=sa.String(length=255),
            nullable=False,
        )
        batch_op.alter_column(
            "display_name_normalized",
            existing_type=sa.String(length=255),
            nullable=False,
        )
        batch_op.drop_column("full_name")
        batch_op.drop_column("full_name_normalized")
        batch_op.drop_column("nickname")
        batch_op.drop_column("nickname_normalized")
        batch_op.create_index(
            batch_op.f("ix_players_display_name_normalized"),
            ["display_name_normalized"],
        )


def downgrade() -> None:
    # The original identity type cannot be reconstructed, so the unified value is
    # restored into full_name and nickname is left empty.
    with op.batch_alter_table("players") as batch_op:
        batch_op.add_column(sa.Column("full_name", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("full_name_normalized", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("nickname", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("nickname_normalized", sa.String(length=100), nullable=True))

    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            UPDATE players
               SET full_name = display_name,
                   full_name_normalized = display_name_normalized,
                   nickname = NULL,
                   nickname_normalized = NULL
            """
        )
    )

    with op.batch_alter_table("players") as batch_op:
        batch_op.drop_index(batch_op.f("ix_players_display_name_normalized"))
        batch_op.drop_column("display_name")
        batch_op.drop_column("display_name_normalized")
        batch_op.create_check_constraint(
            "identity_present",
            "full_name IS NOT NULL OR nickname IS NOT NULL",
        )
        batch_op.create_index(
            batch_op.f("ix_players_full_name_normalized"),
            ["full_name_normalized"],
        )
        batch_op.create_index(
            batch_op.f("ix_players_nickname_normalized"),
            ["nickname_normalized"],
        )


def _player_ids(connection, query: str) -> list[int]:
    return list(connection.execute(sa.text(query)).scalars())


def _normalize_display_name(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.strip().casefold().replace("ё", "е").split())
    return normalized or None
