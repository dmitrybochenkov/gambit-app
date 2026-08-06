"""remove result submission and admin-created registration review

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-08-06 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c5d6e7f8a9b0"
down_revision: str | None = "b4c5d6e7f8a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


REGISTRATION_REQUEST_PAYLOAD = """
(
    request_type = 'new_player'
    AND requested_display_name IS NOT NULL
    AND requested_display_name_normalized IS NOT NULL
    AND requested_link_name IS NULL
    AND candidate_user_id IS NULL
)
OR (
    request_type = 'link_existing_player'
    AND requested_display_name IS NULL
    AND requested_display_name_normalized IS NULL
    AND requested_link_name IS NOT NULL
)
"""


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            DELETE FROM registration_requests
            WHERE request_type = 'admin_created_player_review'
            """
        )
    )

    op.drop_index(
        op.f("ix_registration_requests_tournament_id"),
        table_name="registration_requests",
    )
    op.drop_index(
        op.f("ix_registration_requests_created_by_user_id"),
        table_name="registration_requests",
    )
    op.drop_index(
        op.f("ix_registration_requests_subject_user_id"),
        table_name="registration_requests",
    )
    with op.batch_alter_table("registration_requests") as batch_op:
        batch_op.drop_constraint("registration_request_payload", type_="check")
        batch_op.drop_constraint(
            batch_op.f("fk_registration_requests_tournament_id_tournaments"),
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            batch_op.f("fk_registration_requests_created_by_user_id_users"),
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            batch_op.f("fk_registration_requests_subject_user_id_users"),
            type_="foreignkey",
        )
        batch_op.drop_column("tournament_id")
        batch_op.drop_column("created_by_user_id")
        batch_op.drop_column("subject_user_id")
        batch_op.create_check_constraint(
            "registration_request_payload",
            REGISTRATION_REQUEST_PAYLOAD,
        )

    with op.batch_alter_table("tournaments") as batch_op:
        batch_op.drop_index("ix_tournaments_results_submitted_by_user_id")
        batch_op.drop_constraint(
            "fk_tournaments_results_submitted_by_user_id_users",
            type_="foreignkey",
        )
        batch_op.drop_column("results_submitted_by_user_id")
        batch_op.drop_column("results_submitted_at")


def downgrade() -> None:
    raise RuntimeError(
        "Downgrade is intentionally unsupported because result submission and "
        "admin-created registration review flows were removed from runtime code."
    )
