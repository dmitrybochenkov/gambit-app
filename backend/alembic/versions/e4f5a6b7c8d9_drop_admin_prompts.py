"""drop admin prompts

Revision ID: e4f5a6b7c8d9
Revises: e3f4a5b6c7d8
Create Date: 2026-08-09 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e4f5a6b7c8d9"
down_revision: str | None = "e3f4a5b6c7d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("admin_prompts")


def downgrade() -> None:
    raise RuntimeError("Downgrade is unsupported after removing admin_prompts.")
