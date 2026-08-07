"""strict admin prompt lifecycle

Revision ID: a0b1c2d3e4f5
Revises: f9a0b1c2d3e4
Create Date: 2026-08-06 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a0b1c2d3e4f5"
down_revision: str | None = "f9a0b1c2d3e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


OLD_STATUS = sa.Enum(
    "pending",
    "confirmed",
    "cancelled",
    "needs_changes",
    name="admin_prompt_status",
    native_enum=False,
)
NEW_STATUS = sa.Enum(
    "pending",
    "confirmed",
    "cancelled",
    name="admin_prompt_status",
    native_enum=False,
)
PROMPT_KIND = sa.Enum(
    "tournaments_proposal",
    "season_proposal",
    name="admin_prompt_kind",
    native_enum=False,
)


def upgrade() -> None:
    op.execute(sa.text("DELETE FROM admin_prompts"))
    op.drop_index(op.f("ix_admin_prompts_key"), table_name="admin_prompts")

    with op.batch_alter_table("admin_prompts") as batch_op:
        batch_op.drop_column("notified_at")
        batch_op.drop_column("resolved_by_admin_id")
        batch_op.alter_column(
            "kind",
            existing_type=sa.String(length=60),
            type_=PROMPT_KIND,
            existing_nullable=False,
        )
        batch_op.alter_column(
            "status",
            existing_type=OLD_STATUS,
            type_=NEW_STATUS,
            existing_nullable=False,
        )
        batch_op.add_column(sa.Column("resolved_by_user_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_admin_prompts_resolved_by_user_id_users",
            "users",
            ["resolved_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.create_index(
        op.f("ix_admin_prompts_resolved_by_user_id"),
        "admin_prompts",
        ["resolved_by_user_id"],
    )


def downgrade() -> None:
    raise RuntimeError("Downgrade is unsupported after strict admin prompt lifecycle migration.")
