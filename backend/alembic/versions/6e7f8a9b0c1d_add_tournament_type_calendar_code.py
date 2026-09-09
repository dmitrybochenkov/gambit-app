"""add tournament type calendar code

Revision ID: 6e7f8a9b0c1d
Revises: 5d6e7f8a9b0c
Create Date: 2026-09-09 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "6e7f8a9b0c1d"
down_revision: str | None = "5d6e7f8a9b0c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CALENDAR_CODES = {
    "bounty": "B",
    "bounty_v2": "B2",
    "bounty_v3": "B3",
    "classic": "C",
    "classic_v2": "C2",
    "classic_v3": "C3",
    "freezeout": "F",
    "freezeout_v2": "F2",
    "deep_stack": "D",
    "deep_stack_v2": "D2",
    "double_double": "DD",
    "mystery_bounty": "MB",
    "boss_bounty": "BB",
    "white_party": "WP",
    "main_ko": "MK",
    "legacy_unknown": "?",
}


def upgrade() -> None:
    with op.batch_alter_table("tournament_types") as batch_op:
        batch_op.add_column(sa.Column("calendar_code", sa.String(length=8), nullable=True))

    for code, calendar_code in CALENDAR_CODES.items():
        op.execute(
            sa.text(
                """
                UPDATE tournament_types
                SET calendar_code = :calendar_code
                WHERE code = :code
                """
            ).bindparams(code=code, calendar_code=calendar_code)
        )

    missing_count = (
        op.get_bind()
        .execute(sa.text("SELECT COUNT(*) FROM tournament_types WHERE calendar_code IS NULL"))
        .scalar_one()
    )
    if missing_count:
        raise RuntimeError("tournament_types.calendar_code backfill left NULL values")

    with op.batch_alter_table("tournament_types") as batch_op:
        batch_op.alter_column(
            "calendar_code",
            existing_type=sa.String(length=8),
            nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("tournament_types") as batch_op:
        batch_op.drop_column("calendar_code")
