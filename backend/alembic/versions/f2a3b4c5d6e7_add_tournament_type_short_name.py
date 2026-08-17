"""add tournament type short name

Revision ID: f2a3b4c5d6e7
Revises: f1a2b3c4d5e6
Create Date: 2026-08-17 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f2a3b4c5d6e7"
down_revision: str | None = "f1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SHORT_NAMES = {
    "bounty": "Bounty",
    "classic": "Classic",
    "freezeout": "Freezeout",
    "double_double": "Double",
    "boss_bounty": "Boss",
    "mystery_bounty": "Mystery",
    "legacy_unknown": "Турнир",
}


def upgrade() -> None:
    with op.batch_alter_table("tournament_types") as batch_op:
        batch_op.add_column(sa.Column("short_name", sa.String(length=32), nullable=True))

    for code, short_name in SHORT_NAMES.items():
        op.execute(
            sa.text(
                """
                UPDATE tournament_types
                SET short_name = :short_name
                WHERE code = :code
                """
            ).bindparams(code=code, short_name=short_name)
        )

    connection = op.get_bind()
    missing_count = connection.execute(
        sa.text("SELECT COUNT(*) FROM tournament_types WHERE short_name IS NULL")
    ).scalar_one()
    if missing_count:
        raise RuntimeError("tournament_types.short_name backfill left NULL values")

    with op.batch_alter_table("tournament_types") as batch_op:
        batch_op.alter_column(
            "short_name",
            existing_type=sa.String(length=32),
            nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("tournament_types") as batch_op:
        batch_op.drop_column("short_name")
