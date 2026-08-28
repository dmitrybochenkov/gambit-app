"""add user gender

Revision ID: 3b4c5d6e7f8a
Revises: 2a3b4c5d6e7f
Create Date: 2026-08-28 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "3b4c5d6e7f8a"
down_revision: str | None = "2a3b4c5d6e7f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("gender", sa.String(length=6), nullable=True))
        batch_op.create_check_constraint(
            "users_gender_values",
            "gender IN ('male', 'female') OR gender IS NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("users_gender_values", type_="check")
        batch_op.drop_column("gender")
