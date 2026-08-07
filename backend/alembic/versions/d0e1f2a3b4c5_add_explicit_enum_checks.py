"""add explicit enum checks

Revision ID: d0e1f2a3b4c5
Revises: c0d1e2f3a4b5
Create Date: 2026-08-07 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d0e1f2a3b4c5"
down_revision: str | None = "c0d1e2f3a4b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.create_check_constraint(
            "users_role_values",
            "role IN ('player', 'admin', 'superadmin')",
        )
        batch_op.create_check_constraint(
            "users_status_values",
            "status IN ('active', 'blocked')",
        )

    with op.batch_alter_table("tournaments") as batch_op:
        batch_op.create_check_constraint(
            "tournaments_status_values",
            "status IN ('active', 'closed', 'cancelled')",
        )

    with op.batch_alter_table("tournament_types") as batch_op:
        batch_op.create_check_constraint(
            "tournament_types_status_values",
            "status IN ('active', 'archived')",
        )

    with op.batch_alter_table("tournament_type_rules") as batch_op:
        batch_op.create_check_constraint(
            "tournament_type_rules_knockout_mode_values",
            "knockout_mode IN ('none', 'small', 'small_big')",
        )

    with op.batch_alter_table("registration_requests") as batch_op:
        batch_op.create_check_constraint(
            "registration_requests_request_type_values",
            "request_type IN ('new_player', 'link_existing_player')",
        )
        batch_op.create_check_constraint(
            "registration_requests_status_values",
            "status IN ('pending', 'approved', 'rejected')",
        )


def downgrade() -> None:
    raise RuntimeError("Downgrade is unsupported after explicit enum checks migration.")
