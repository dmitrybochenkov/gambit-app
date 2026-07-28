"""remove season status

Revision ID: d9e0f1a2b3c4
Revises: c7d8e9f0a1b2
Create Date: 2026-07-28 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d9e0f1a2b3c4"
down_revision: str | None = "c7d8e9f0a1b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEASON_DATE_RANGE_CONSTRAINT = "ends_at IS NULL OR ends_at >= starts_at"

SEASON_STATUS_DATES_CONSTRAINT = """
(status = 'active' AND (ends_at IS NULL OR starts_at <= ends_at))
OR (
    status = 'closed'
    AND ends_at IS NOT NULL
    AND starts_at <= ends_at
)
"""


def upgrade() -> None:
    op.drop_index("uq_seasons_open_ended", table_name="seasons")
    op.drop_index(op.f("ix_seasons_status"), table_name="seasons")
    with op.batch_alter_table("seasons", recreate="always") as batch_op:
        batch_op.drop_constraint("date_range", type_="check")
        batch_op.drop_column("status")
        batch_op.create_check_constraint("date_range", SEASON_DATE_RANGE_CONSTRAINT)
    op.create_index(
        "uq_seasons_open_ended",
        "seasons",
        [sa.literal_column("1")],
        unique=True,
        sqlite_where=sa.text("ends_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_seasons_open_ended", table_name="seasons")
    with op.batch_alter_table("seasons", recreate="always") as batch_op:
        batch_op.drop_constraint("date_range", type_="check")
        batch_op.add_column(
            sa.Column(
                "status",
                sa.String(length=6),
                nullable=False,
                server_default="active",
            )
        )
        batch_op.create_check_constraint(
            "date_range",
            SEASON_STATUS_DATES_CONSTRAINT,
        )

    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            UPDATE seasons
            SET status = 'closed'
            WHERE ends_at IS NOT NULL
            """
        )
    )

    op.create_index(op.f("ix_seasons_status"), "seasons", ["status"], unique=False)
    op.create_index(
        "uq_seasons_open_ended",
        "seasons",
        ["status"],
        unique=True,
        sqlite_where=sa.text("ends_at IS NULL"),
    )
