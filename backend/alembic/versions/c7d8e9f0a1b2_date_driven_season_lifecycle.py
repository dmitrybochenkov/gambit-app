"""date driven season lifecycle

Revision ID: c7d8e9f0a1b2
Revises: b1c2d3e4f5a6
Create Date: 2026-07-28 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c7d8e9f0a1b2"
down_revision: str | None = "b1c2d3e4f5a6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEASON_DATE_RANGE_CONSTRAINT = """
(status = 'active' AND (ends_at IS NULL OR starts_at <= ends_at))
OR (
    status = 'closed'
    AND ends_at IS NOT NULL
    AND starts_at <= ends_at
)
"""

SEASON_STATUS_DATES_CONSTRAINT = """
(status = 'active' AND ends_at IS NULL)
OR (
    status = 'closed'
    AND ends_at IS NOT NULL
    AND starts_at <= ends_at
)
"""


def upgrade() -> None:
    op.drop_index("uq_seasons_active", table_name="seasons")
    with op.batch_alter_table("seasons", recreate="always") as batch_op:
        batch_op.drop_constraint("status_dates_consistent", type_="check")
        batch_op.create_check_constraint("date_range", SEASON_DATE_RANGE_CONSTRAINT)
    op.create_index(
        "uq_seasons_open_ended",
        "seasons",
        ["status"],
        unique=True,
        sqlite_where=sa.text("ends_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_seasons_open_ended", table_name="seasons")
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
                    ends_at = COALESCE(ends_at, starts_at)
                WHERE status = 'active' AND id != :keep_active_id
                """
            ),
            {"keep_active_id": keep_active["id"]},
        )
        connection.execute(
            sa.text("UPDATE seasons SET ends_at = NULL WHERE id = :keep_active_id"),
            {"keep_active_id": keep_active["id"]},
        )

    with op.batch_alter_table("seasons", recreate="always") as batch_op:
        batch_op.drop_constraint("date_range", type_="check")
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
