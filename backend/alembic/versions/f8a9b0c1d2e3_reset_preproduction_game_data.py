"""reset pre-production game data before strict tournament schema

Revision ID: f8a9b0c1d2e3
Revises: e7f8a9b0c1d2
Create Date: 2026-08-06 00:00:00.000000

This destructive migration intentionally removes pre-production game data.
Historical users, tournaments, results, and rating are re-importable from the
project import sources, so no backup tables are created here.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f8a9b0c1d2e3"
down_revision: str | None = "e7f8a9b0c1d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("DELETE FROM tournament_results"))
    op.execute(sa.text("DELETE FROM tournament_registrations"))
    op.execute(sa.text("DELETE FROM tournaments"))
    op.execute(sa.text("DELETE FROM admin_prompts"))


def downgrade() -> None:
    raise RuntimeError("Downgrade is unsupported after destructive pre-production game data reset.")
