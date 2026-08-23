"""enable mystery bounty knockouts

Revision ID: f6d7e8f9a0b1
Revises: f5c6d7e8f9a0
Create Date: 2026-08-23 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f6d7e8f9a0b1"
down_revision: str | None = "f5c6d7e8f9a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE tournament_type_rules
            SET knockout_mode = 'small'
            WHERE tournament_type_id = (
                SELECT id FROM tournament_types WHERE code = 'mystery_bounty'
            )
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE tournament_type_rules
            SET knockout_mode = 'none'
            WHERE tournament_type_id = (
                SELECT id FROM tournament_types WHERE code = 'mystery_bounty'
            )
            """
        )
    )
