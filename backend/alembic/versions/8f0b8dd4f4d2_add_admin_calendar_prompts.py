"""add admin calendar prompts

Revision ID: 8f0b8dd4f4d2
Revises: 2ce4d6b5027c
Create Date: 2026-07-08 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "8f0b8dd4f4d2"
down_revision: str | None = "2ce4d6b5027c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "admin_prompts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=60), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "confirmed",
                "cancelled",
                "needs_changes",
                name="admin_prompt_status",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by_admin_id", sa.Integer(), nullable=True),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admin_prompts")),
        sa.UniqueConstraint("key", name=op.f("uq_admin_prompts_key")),
    )
    op.create_index(op.f("ix_admin_prompts_key"), "admin_prompts", ["key"], unique=True)
    op.create_index(op.f("ix_admin_prompts_kind"), "admin_prompts", ["kind"], unique=False)
    op.create_index(op.f("ix_admin_prompts_status"), "admin_prompts", ["status"], unique=False)

    op.execute(
        sa.text(
            """
            INSERT OR IGNORE INTO seasons (name, scoring_config_id, starts_at, ends_at, status)
            SELECT :name, id, :starts_at, :ends_at, :status
            FROM scoring_configs
            ORDER BY id
            LIMIT 1
            """
        ).bindparams(
            name="Сезон 1",
            starts_at="2025-10-16",
            ends_at="2026-01-25",
            status="closed",
        )
    )
    op.execute(
        sa.text(
            """
            INSERT OR IGNORE INTO seasons (name, scoring_config_id, starts_at, ends_at, status)
            SELECT :name, id, :starts_at, :ends_at, :status
            FROM scoring_configs
            ORDER BY id
            LIMIT 1
            """
        ).bindparams(
            name="Сезон 2",
            starts_at="2026-01-27",
            ends_at="2026-05-31",
            status="closed",
        )
    )
    op.execute(
        sa.text(
            """
            INSERT OR IGNORE INTO seasons (name, scoring_config_id, starts_at, ends_at, status)
            SELECT :name, id, :starts_at, :ends_at, :status
            FROM scoring_configs
            ORDER BY id
            LIMIT 1
            """
        ).bindparams(
            name="Лето 2026",
            starts_at="2026-06-01",
            ends_at="2026-08-31",
            status="active",
        )
    )
    op.execute("UPDATE seasons SET status = 'closed' WHERE name != 'Лето 2026'")
    op.execute("UPDATE seasons SET status = 'active' WHERE name = 'Лето 2026'")
    op.execute(
        """
        UPDATE tournaments
        SET season_id = (SELECT id FROM seasons WHERE name = 'Лето 2026')
        WHERE date >= '2026-06-01' AND date <= '2026-08-31'
        """
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_admin_prompts_status"), table_name="admin_prompts")
    op.drop_index(op.f("ix_admin_prompts_kind"), table_name="admin_prompts")
    op.drop_index(op.f("ix_admin_prompts_key"), table_name="admin_prompts")
    op.drop_table("admin_prompts")
