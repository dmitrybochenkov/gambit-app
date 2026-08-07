"""cleanup registration schema

Revision ID: b0c1d2e3f4a5
Revises: a0b1c2d3e4f5
Create Date: 2026-08-07 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b0c1d2e3f4a5"
down_revision: str | None = "a0b1c2d3e4f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("DELETE FROM registration_requests WHERE telegram_id IS NULL"))

    with op.batch_alter_table("tournament_registrations") as batch_op:
        batch_op.drop_column("updated_at")

    with op.batch_alter_table("registration_requests") as batch_op:
        batch_op.alter_column(
            "telegram_id",
            existing_type=sa.BigInteger(),
            nullable=False,
        )
        batch_op.drop_column("rejection_reason")


def downgrade() -> None:
    raise RuntimeError("Downgrade is unsupported after removing unused registration schema fields.")
