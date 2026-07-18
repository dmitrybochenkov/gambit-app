"""remove rejected players state

Revision ID: 6b17d41e9c2a
Revises: 9c8e7b4a1d2f
Create Date: 2026-07-15 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "6b17d41e9c2a"
down_revision: str | None = "9c8e7b4a1d2f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    rejected_count = connection.execute(
        sa.text("SELECT COUNT(*) FROM players WHERE status = 'rejected'")
    ).scalar_one()
    if rejected_count:
        raise RuntimeError(
            "Cannot remove rejected player state while rejected players exist."
        )

    existing_columns = {
        column["name"] for column in sa.inspect(connection).get_columns("players")
    }
    columns_to_drop = [
        column
        for column in ["rejection_reason", "rejected_by_admin_id", "rejected_at"]
        if column in existing_columns
    ]
    if not columns_to_drop:
        return

    with op.batch_alter_table("players", recreate="always") as batch_op:
        for column in columns_to_drop:
            batch_op.drop_column(column)


def downgrade() -> None:
    with op.batch_alter_table("players", recreate="always") as batch_op:
        batch_op.add_column(sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("rejected_by_admin_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("rejection_reason", sa.String(length=500), nullable=True))
        batch_op.create_foreign_key(
            batch_op.f("fk_players_rejected_by_admin_id_players"),
            "players",
            ["rejected_by_admin_id"],
            ["id"],
            ondelete="SET NULL",
        )
