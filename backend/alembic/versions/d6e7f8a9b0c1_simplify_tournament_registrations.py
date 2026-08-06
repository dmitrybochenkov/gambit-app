"""simplify tournament registrations

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-08-06 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d6e7f8a9b0c1"
down_revision: str | None = "c5d6e7f8a9b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DELETE FROM tournament_registrations WHERE status = 'cancelled'")

    duplicates = op.get_bind().execute(
        sa.text(
            """
            SELECT tournament_id, player_id, COUNT(*)
            FROM tournament_registrations
            GROUP BY tournament_id, player_id
            HAVING COUNT(*) > 1
            """
        )
    )
    duplicate_rows = duplicates.fetchall()
    if duplicate_rows:
        raise RuntimeError("Duplicate tournament registrations found before simplification.")

    with op.batch_alter_table("tournament_registrations") as batch_op:
        batch_op.drop_index("ix_tournament_registrations_status")
        batch_op.drop_constraint("cancellation_state", type_="check")
        batch_op.add_column(sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))

    op.execute(
        """
        UPDATE tournament_registrations
        SET created_at = registered_at,
            updated_at = registered_at
        """
    )

    with op.batch_alter_table("tournament_registrations") as batch_op:
        batch_op.alter_column(
            "created_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
        )
        batch_op.alter_column(
            "updated_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
        )
        batch_op.drop_column("cancelled_at")
        batch_op.drop_column("registered_at")
        batch_op.drop_column("status")


def downgrade() -> None:
    raise RuntimeError(
        "Downgrade is intentionally unsupported because cancelled registration history "
        "is discarded by this migration."
    )
