"""replace players with users

Revision ID: e7a9c1d4f2b6
Revises: c4f2a9b8d1e7
Create Date: 2026-07-27 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e7a9c1d4f2b6"
down_revision: str | None = "c4f2a9b8d1e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()

    op.drop_table("registration_matches")
    connection.execute(sa.text("DELETE FROM players WHERE status = 'pending'"))
    connection.execute(sa.text("UPDATE players SET telegram_id = NULL WHERE telegram_id < 0"))
    connection.execute(sa.text("UPDATE players SET role = 'player' WHERE role = 'user'"))
    op.rename_table("players", "users")

    with op.batch_alter_table("users", recreate="always") as batch_op:
        batch_op.drop_constraint("fk_players_approved_by_admin_id_players", type_="foreignkey")
        batch_op.drop_index("ix_players_display_name_normalized")
        batch_op.drop_index("ix_players_status")
        batch_op.drop_index("ix_players_telegram_id")
        batch_op.alter_column(
            "telegram_id",
            existing_type=sa.BigInteger(),
            nullable=True,
        )
        batch_op.drop_column("approved_by_admin_id")
        batch_op.drop_column("approved_at")
        batch_op.create_unique_constraint(
            "uq_users_display_name_normalized",
            ["display_name_normalized"],
        )
        batch_op.create_index("ix_users_telegram_id", ["telegram_id"], unique=True)
        batch_op.create_index("ix_users_status", ["status"])
        batch_op.create_index("ix_users_role", ["role"])

    _retarget_player_fk(
        table_name="tournament_registrations",
        old_fk_name="fk_tournament_registrations_player_id_players",
        ondelete="CASCADE",
    )
    _retarget_player_fk(
        table_name="tournament_results",
        old_fk_name="fk_tournament_results_player_id_players",
        ondelete="RESTRICT",
    )
    _retarget_player_fk(
        table_name="tournament_result_drafts",
        old_fk_name="fk_tournament_result_drafts_player_id_players",
        ondelete="CASCADE",
    )

    op.create_table(
        "registration_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "request_type",
            sa.Enum(
                "new_player",
                "link_existing_player",
                name="registration_request_type",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "approved",
                "rejected",
                name="registration_request_status",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("requested_display_name", sa.String(length=255), nullable=True),
        sa.Column("requested_display_name_normalized", sa.String(length=255), nullable=True),
        sa.Column("requested_link_name", sa.String(length=255), nullable=True),
        sa.Column("candidate_user_id", sa.Integer(), nullable=True),
        sa.Column("rejection_reason", sa.String(length=500), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            """
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
            """,
            name=op.f("ck_registration_requests_registration_request_payload"),
        ),
        sa.CheckConstraint(
            """
            (status = 'pending' AND reviewed_at IS NULL)
            OR (status IN ('approved', 'rejected') AND reviewed_at IS NOT NULL)
            """,
            name=op.f("ck_registration_requests_registration_request_review_state"),
        ),
        sa.ForeignKeyConstraint(
            ["candidate_user_id"],
            ["users.id"],
            name=op.f("fk_registration_requests_candidate_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_registration_requests")),
    )
    op.create_index(
        op.f("ix_registration_requests_candidate_user_id"),
        "registration_requests",
        ["candidate_user_id"],
    )
    op.create_index(
        op.f("ix_registration_requests_request_type"),
        "registration_requests",
        ["request_type"],
    )
    op.create_index(
        op.f("ix_registration_requests_status"),
        "registration_requests",
        ["status"],
    )
    op.create_index(
        op.f("ix_registration_requests_telegram_id"),
        "registration_requests",
        ["telegram_id"],
    )
    op.create_index(
        "uq_registration_requests_pending_telegram_id",
        "registration_requests",
        ["telegram_id"],
        unique=True,
        sqlite_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "uq_registration_requests_pending_new_display_name",
        "registration_requests",
        ["requested_display_name_normalized"],
        unique=True,
        sqlite_where=sa.text("status = 'pending' AND request_type = 'new_player'"),
    )


def downgrade() -> None:
    # This migration intentionally drops pending players and registration matches
    # while replacing the old Player registration model with User/RegistrationRequest.
    # Production rollback must restore the previous application version together
    # with a database backup, not run alembic downgrade through this revision.
    raise NotImplementedError("Downgrade to the old Player registration model is not supported.")


def _retarget_player_fk(table_name: str, old_fk_name: str, ondelete: str) -> None:
    with op.batch_alter_table(table_name, recreate="always") as batch_op:
        batch_op.drop_constraint(old_fk_name, type_="foreignkey")
        batch_op.create_foreign_key(
            batch_op.f(f"fk_{table_name}_player_id_users"),
            "users",
            ["player_id"],
            ["id"],
            ondelete=ondelete,
        )
