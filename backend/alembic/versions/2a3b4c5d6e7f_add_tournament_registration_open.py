"""add tournament registration open flag

Revision ID: 2a3b4c5d6e7f
Revises: 190f0bbcf1e2
Create Date: 2026-08-27 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "2a3b4c5d6e7f"
down_revision: str | None = "190f0bbcf1e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("tournaments") as batch_op:
        batch_op.add_column(
            sa.Column(
                "registration_open",
                sa.Boolean(),
                server_default=sa.true(),
                nullable=False,
            )
        )
        batch_op.create_index(
            batch_op.f("ix_tournaments_registration_open"),
            ["registration_open"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("tournaments") as batch_op:
        batch_op.drop_index(batch_op.f("ix_tournaments_registration_open"))
        batch_op.drop_column("registration_open")
