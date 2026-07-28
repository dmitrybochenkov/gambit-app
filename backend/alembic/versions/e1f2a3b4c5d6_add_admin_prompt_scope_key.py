"""add admin prompt scope key

Revision ID: e1f2a3b4c5d6
Revises: d9e0f1a2b3c4
Create Date: 2026-07-28 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e1f2a3b4c5d6"
down_revision: str | None = "d9e0f1a2b3c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PENDING_WEEKLY_SCOPE_FILTER = "status = 'pending' AND scope_key IS NOT NULL"


def upgrade() -> None:
    with op.batch_alter_table("admin_prompts") as batch_op:
        batch_op.add_column(sa.Column("scope_key", sa.String(length=160), nullable=True))

    op.execute(
        sa.text(
            """
            UPDATE admin_prompts
            SET scope_key = key
            WHERE kind = 'tournaments_proposal'
              AND key LIKE 'tournaments:%:%'
              AND scope_key IS NULL
            """
        )
    )

    op.create_index(
        op.f("ix_admin_prompts_scope_key"),
        "admin_prompts",
        ["scope_key"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_prompts_kind_scope_status"),
        "admin_prompts",
        ["kind", "scope_key", "status"],
        unique=False,
    )
    op.create_index(
        op.f("uq_admin_prompts_pending_scope"),
        "admin_prompts",
        ["kind", "scope_key"],
        unique=True,
        sqlite_where=sa.text(PENDING_WEEKLY_SCOPE_FILTER),
        postgresql_where=sa.text(PENDING_WEEKLY_SCOPE_FILTER),
    )


def downgrade() -> None:
    op.drop_index(op.f("uq_admin_prompts_pending_scope"), table_name="admin_prompts")
    op.drop_index(op.f("ix_admin_prompts_kind_scope_status"), table_name="admin_prompts")
    op.drop_index(op.f("ix_admin_prompts_scope_key"), table_name="admin_prompts")
    with op.batch_alter_table("admin_prompts") as batch_op:
        batch_op.drop_column("scope_key")
