"""add tournament participants

Revision ID: f6a7b8c9d0e1
Revises: e1f2a3b4c5d6
Create Date: 2026-07-29 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: str | None = "e1f2a3b4c5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


OLD_REGISTRATION_REQUEST_PAYLOAD = """
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

NEW_REGISTRATION_REQUEST_PAYLOAD = """
(
    request_type = 'new_player'
    AND requested_display_name IS NOT NULL
    AND requested_display_name_normalized IS NOT NULL
    AND requested_link_name IS NULL
    AND candidate_user_id IS NULL
    AND subject_user_id IS NULL
    AND created_by_user_id IS NULL
    AND tournament_id IS NULL
)
OR (
    request_type = 'link_existing_player'
    AND requested_display_name IS NULL
    AND requested_display_name_normalized IS NULL
    AND requested_link_name IS NOT NULL
    AND subject_user_id IS NULL
    AND created_by_user_id IS NULL
    AND tournament_id IS NULL
)
OR (
    request_type = 'admin_created_player_review'
    AND telegram_id IS NULL
    AND requested_display_name IS NULL
    AND requested_display_name_normalized IS NULL
    AND requested_link_name IS NULL
    AND candidate_user_id IS NULL
    AND subject_user_id IS NOT NULL
    AND created_by_user_id IS NOT NULL
)
"""


def upgrade() -> None:
    with op.batch_alter_table("registration_requests") as batch_op:
        batch_op.drop_constraint("registration_request_payload", type_="check")
        batch_op.alter_column(
            "telegram_id",
            existing_type=sa.BigInteger(),
            nullable=True,
        )
        batch_op.add_column(sa.Column("subject_user_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("created_by_user_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("tournament_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            batch_op.f("fk_registration_requests_subject_user_id_users"),
            "users",
            ["subject_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            batch_op.f("fk_registration_requests_created_by_user_id_users"),
            "users",
            ["created_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            batch_op.f("fk_registration_requests_tournament_id_tournaments"),
            "tournaments",
            ["tournament_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_check_constraint(
            "registration_request_payload",
            NEW_REGISTRATION_REQUEST_PAYLOAD,
        )

    op.create_index(
        op.f("ix_registration_requests_subject_user_id"),
        "registration_requests",
        ["subject_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_registration_requests_created_by_user_id"),
        "registration_requests",
        ["created_by_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_registration_requests_tournament_id"),
        "registration_requests",
        ["tournament_id"],
        unique=False,
    )

    op.create_table(
        "tournament_participants",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tournament_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("checked_in_by_user_id", sa.Integer(), nullable=True),
        sa.Column("checked_in_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["checked_in_by_user_id"],
            ["users.id"],
            name=op.f("fk_tournament_participants_checked_in_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tournament_id"],
            ["tournaments.id"],
            name=op.f("fk_tournament_participants_tournament_id_tournaments"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_tournament_participants_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tournament_participants")),
        sa.UniqueConstraint(
            "tournament_id",
            "user_id",
            name=op.f("uq_tournament_participants_tournament_user"),
        ),
    )
    op.create_index(
        op.f("ix_tournament_participants_checked_in_by_user_id"),
        "tournament_participants",
        ["checked_in_by_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tournament_participants_source"),
        "tournament_participants",
        ["source"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tournament_participants_tournament_id"),
        "tournament_participants",
        ["tournament_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tournament_participants_user_id"),
        "tournament_participants",
        ["user_id"],
        unique=False,
    )

    op.execute(
        sa.text(
            """
            INSERT INTO tournament_participants (
                tournament_id,
                user_id,
                source,
                checked_in_by_user_id,
                checked_in_at,
                created_at,
                updated_at
            )
            SELECT DISTINCT
                tournament_id,
                player_id,
                'migrated_result',
                NULL,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            FROM tournament_results
            """
        )
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_tournament_participants_user_id"),
        table_name="tournament_participants",
    )
    op.drop_index(
        op.f("ix_tournament_participants_tournament_id"),
        table_name="tournament_participants",
    )
    op.drop_index(
        op.f("ix_tournament_participants_source"),
        table_name="tournament_participants",
    )
    op.drop_index(
        op.f("ix_tournament_participants_checked_in_by_user_id"),
        table_name="tournament_participants",
    )
    op.drop_table("tournament_participants")

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
        batch_op.alter_column(
            "telegram_id",
            existing_type=sa.BigInteger(),
            nullable=False,
        )
        batch_op.create_check_constraint(
            "registration_request_payload",
            OLD_REGISTRATION_REQUEST_PAYLOAD,
        )
