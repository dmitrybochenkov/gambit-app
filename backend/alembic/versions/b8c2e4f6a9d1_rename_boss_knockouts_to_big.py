"""rename boss knockouts to big

Revision ID: b8c2e4f6a9d1
Revises: 3a9d4b8e1f02
Create Date: 2026-07-19 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8c2e4f6a9d1"
down_revision: str | None = "3a9d4b8e1f02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("tournament_results") as batch_op:
        batch_op.drop_constraint(
            "boss_knockouts_count_nonnegative",
            type_="check",
        )
        batch_op.alter_column(
            "boss_knockouts_count",
            new_column_name="big_knockouts_count",
            existing_type=sa.Integer(),
            existing_nullable=False,
        )
        batch_op.create_check_constraint(
            "big_knockouts_count_nonnegative",
            "big_knockouts_count >= 0",
        )

    with op.batch_alter_table("tournament_result_drafts") as batch_op:
        batch_op.drop_constraint(
            "boss_knockouts_count_nonnegative",
            type_="check",
        )
        batch_op.alter_column(
            "boss_knockouts_count",
            new_column_name="big_knockouts_count",
            existing_type=sa.Integer(),
            existing_nullable=False,
        )
        batch_op.create_check_constraint(
            "big_knockouts_count_nonnegative",
            "big_knockouts_count >= 0",
        )


def downgrade() -> None:
    with op.batch_alter_table("tournament_result_drafts") as batch_op:
        batch_op.drop_constraint(
            "big_knockouts_count_nonnegative",
            type_="check",
        )
        batch_op.alter_column(
            "big_knockouts_count",
            new_column_name="boss_knockouts_count",
            existing_type=sa.Integer(),
            existing_nullable=False,
        )
        batch_op.create_check_constraint(
            "boss_knockouts_count_nonnegative",
            "boss_knockouts_count >= 0",
        )

    with op.batch_alter_table("tournament_results") as batch_op:
        batch_op.drop_constraint(
            "big_knockouts_count_nonnegative",
            type_="check",
        )
        batch_op.alter_column(
            "big_knockouts_count",
            new_column_name="boss_knockouts_count",
            existing_type=sa.Integer(),
            existing_nullable=False,
        )
        batch_op.create_check_constraint(
            "boss_knockouts_count_nonnegative",
            "boss_knockouts_count >= 0",
        )
