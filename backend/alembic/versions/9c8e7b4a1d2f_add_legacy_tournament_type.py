"""add legacy tournament type

Revision ID: 9c8e7b4a1d2f
Revises: 7f3a2d8b9c1e
Create Date: 2026-07-13 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "9c8e7b4a1d2f"
down_revision: str | None = "7f3a2d8b9c1e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO tournament_types (
                code, name, description, status, created_at, updated_at
            )
            SELECT
                'legacy_unknown',
                'Неопределенный турнир',
                'Исторический турнир из старой таблицы результатов.',
                'active',
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            WHERE NOT EXISTS (
                SELECT 1 FROM tournament_types WHERE code = 'legacy_unknown'
            )
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO tournament_type_rules (
                tournament_type_id,
                points_multiplier,
                prize_place_multiplier,
                prize_place_multiplier_places,
                knockout_mode,
                created_at,
                updated_at
            )
            SELECT id, 1.00, 1.00, NULL, 'none', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            FROM tournament_types
            WHERE code = 'legacy_unknown'
              AND NOT EXISTS (
                  SELECT 1
                  FROM tournament_type_rules
                  WHERE tournament_type_id = tournament_types.id
              )
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DELETE FROM tournament_type_rules
            WHERE tournament_type_id IN (
                SELECT id FROM tournament_types WHERE code = 'legacy_unknown'
            )
            """
        )
    )
    op.execute("DELETE FROM tournament_types WHERE code = 'legacy_unknown'")
