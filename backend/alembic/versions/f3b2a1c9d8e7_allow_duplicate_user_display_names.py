"""allow duplicate user display names

Revision ID: f3b2a1c9d8e7
Revises: e7a9c1d4f2b6
Create Date: 2026-07-27 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f3b2a1c9d8e7"
down_revision: str | None = "e7a9c1d4f2b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users", recreate="always") as batch_op:
        batch_op.drop_constraint("uq_users_display_name_normalized", type_="unique")
        batch_op.create_index("ix_users_display_name_normalized", ["display_name_normalized"])

    op.drop_index(
        "uq_registration_requests_pending_new_display_name",
        table_name="registration_requests",
    )


def downgrade() -> None:
    op.create_index(
        "uq_registration_requests_pending_new_display_name",
        "registration_requests",
        ["requested_display_name_normalized"],
        unique=True,
        sqlite_where=sa.text("status = 'pending' AND request_type = 'new_player'"),
    )

    with op.batch_alter_table("users", recreate="always") as batch_op:
        batch_op.drop_index("ix_users_display_name_normalized")
        batch_op.create_unique_constraint(
            "uq_users_display_name_normalized",
            ["display_name_normalized"],
        )
