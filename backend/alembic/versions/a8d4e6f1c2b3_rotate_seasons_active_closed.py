"""rotate seasons with active and closed states

Revision ID: a8d4e6f1c2b3
Revises: f3b2a1c9d8e7
Create Date: 2026-07-27 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a8d4e6f1c2b3"
down_revision: str | None = "f3b2a1c9d8e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEASON_STATUS_DATES_CONSTRAINT = """
(status = 'active' AND ends_at IS NULL)
OR (
    status = 'closed'
    AND ends_at IS NOT NULL
    AND starts_at <= ends_at
)
"""


def upgrade() -> None:
    with op.batch_alter_table("seasons", recreate="always") as batch_op:
        batch_op.drop_constraint("date_range", type_="check")
        batch_op.alter_column(
            "ends_at",
            existing_type=sa.Date(),
            nullable=True,
        )

    connection = op.get_bind()
    active_seasons = list(
        connection.execute(
            sa.text(
                """
                SELECT id, starts_at
                FROM seasons
                WHERE status = 'active'
                ORDER BY starts_at DESC, id DESC
                """
            )
        ).mappings()
    )
    if active_seasons:
        keep_active = active_seasons[0]
        connection.execute(
            sa.text(
                """
                UPDATE seasons
                SET status = 'closed',
                    ends_at = CASE
                        WHEN starts_at <= date(:keep_starts_at, '-1 day')
                        THEN date(:keep_starts_at, '-1 day')
                        ELSE starts_at
                    END
                WHERE status = 'active' AND id != :keep_active_id
                """
            ),
            {
                "keep_active_id": keep_active["id"],
                "keep_starts_at": keep_active["starts_at"],
            },
        )
        connection.execute(
            sa.text("UPDATE seasons SET ends_at = NULL WHERE id = :keep_active_id"),
            {"keep_active_id": keep_active["id"]},
        )

    connection.execute(
        sa.text(
            """
            UPDATE seasons
            SET status = 'closed',
                ends_at = COALESCE(ends_at, starts_at)
            WHERE status != 'active'
            """
        )
    )
    connection.execute(
        sa.text(
            """
            UPDATE seasons
            SET ends_at = starts_at
            WHERE status = 'closed' AND ends_at < starts_at
            """
        )
    )

    with op.batch_alter_table("seasons", recreate="always") as batch_op:
        batch_op.create_check_constraint(
            "status_dates_consistent",
            SEASON_STATUS_DATES_CONSTRAINT,
        )

    op.create_index(
        "uq_seasons_active",
        "seasons",
        ["status"],
        unique=True,
        sqlite_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index("uq_seasons_active", table_name="seasons")

    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            UPDATE seasons
            SET ends_at = starts_at
            WHERE status = 'active' AND ends_at IS NULL
            """
        )
    )

    with op.batch_alter_table("seasons", recreate="always") as batch_op:
        batch_op.drop_constraint("status_dates_consistent", type_="check")
        batch_op.create_check_constraint("date_range", "starts_at <= ends_at")
        batch_op.alter_column(
            "ends_at",
            existing_type=sa.Date(),
            nullable=False,
        )
