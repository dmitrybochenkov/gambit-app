"""add result draft bonus points

Revision ID: a2b3c4d5e6f7
Revises: f6a7b8c9d0e1
Create Date: 2026-07-29 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a2b3c4d5e6f7"
down_revision: str | None = "f6a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("tournament_type_rules") as batch_op:
        batch_op.add_column(
            sa.Column(
                "supports_bonus_points",
                sa.Boolean(),
                server_default=sa.false(),
                nullable=False,
            )
        )

    op.execute(
        sa.text(
            """
            UPDATE tournament_type_rules
            SET supports_bonus_points = 1
            WHERE tournament_type_id = (
                SELECT id FROM tournament_types WHERE code = 'mystery_bounty'
            )
            """
        )
    )

    with op.batch_alter_table("tournament_result_drafts") as batch_op:
        batch_op.add_column(
            sa.Column(
                "bonus_points",
                sa.Integer(),
                server_default="0",
                nullable=False,
            )
        )
        batch_op.create_check_constraint(
            "bonus_points_nonnegative",
            "bonus_points >= 0",
        )

    with op.batch_alter_table("tournament_participants") as batch_op:
        batch_op.add_column(
            sa.Column(
                "result_status",
                sa.String(length=20),
                server_default="active",
                nullable=False,
            )
        )
        batch_op.create_index(
            "ix_tournament_participants_result_status",
            ["result_status"],
        )

    with op.batch_alter_table("tournaments") as batch_op:
        batch_op.add_column(
            sa.Column(
                "results_submitted_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "results_submitted_by_user_id",
                sa.Integer(),
                nullable=True,
            )
        )
        batch_op.create_foreign_key(
            "fk_tournaments_results_submitted_by_user_id_users",
            "users",
            ["results_submitted_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_tournaments_results_submitted_by_user_id",
            ["results_submitted_by_user_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("tournaments") as batch_op:
        batch_op.drop_index("ix_tournaments_results_submitted_by_user_id")
        batch_op.drop_constraint(
            "fk_tournaments_results_submitted_by_user_id_users",
            type_="foreignkey",
        )
        batch_op.drop_column("results_submitted_by_user_id")
        batch_op.drop_column("results_submitted_at")

    with op.batch_alter_table("tournament_participants") as batch_op:
        batch_op.drop_index("ix_tournament_participants_result_status")
        batch_op.drop_column("result_status")

    with op.batch_alter_table("tournament_result_drafts") as batch_op:
        batch_op.drop_constraint("bonus_points_nonnegative", type_="check")
        batch_op.drop_column("bonus_points")

    with op.batch_alter_table("tournament_type_rules") as batch_op:
        batch_op.drop_column("supports_bonus_points")
