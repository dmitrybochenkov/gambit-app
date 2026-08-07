"""restrict admin prompt resolver foreign key

Revision ID: e2f3a4b5c6d7
Revises: d0e1f2a3b4c5
Create Date: 2026-08-07 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e2f3a4b5c6d7"
down_revision: str | None = "d0e1f2a3b4c5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


FK_NAME = "fk_admin_prompts_resolved_by_user_id_users"


def upgrade() -> None:
    with op.batch_alter_table("admin_prompts") as batch_op:
        batch_op.drop_constraint(FK_NAME, type_="foreignkey")
        batch_op.create_foreign_key(
            FK_NAME,
            "users",
            ["resolved_by_user_id"],
            ["id"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    raise RuntimeError(
        "Downgrade is unsupported after restricting admin prompt resolver foreign key."
    )
