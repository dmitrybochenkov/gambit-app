"""restrict tournaments to active and closed statuses

Revision ID: e5f6a7b8c9d0
Revises: e4f5a6b7c8d9
Create Date: 2026-08-10 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: str | None = "e4f5a6b7c8d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    cancelled_count = connection.exec_driver_sql(
        "SELECT COUNT(*) FROM tournaments WHERE status = 'cancelled'"
    ).scalar_one()
    if cancelled_count:
        raise RuntimeError(
            "Cannot restrict tournaments.status while cancelled tournaments exist. "
            "Delete or resolve cancelled tournament rows before migration."
        )

    with op.batch_alter_table("tournaments") as batch_op:
        batch_op.drop_constraint("tournaments_status_values", type_="check")
        batch_op.create_check_constraint(
            "tournaments_status_values",
            "status IN ('active', 'closed')",
        )


def downgrade() -> None:
    raise RuntimeError("Downgrade is unsupported after tournament status cleanup.")
