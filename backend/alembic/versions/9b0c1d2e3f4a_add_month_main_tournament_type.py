"""add Month Main tournament type

Revision ID: 9b0c1d2e3f4a
Revises: 8a9b0c1d2e3f
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "9b0c1d2e3f4a"
down_revision: str | None = "8a9b0c1d2e3f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    if connection.execute(
        sa.text("SELECT 1 FROM tournament_types WHERE code = 'month_main'")
    ).first():
        return
    connection.execute(
        sa.text(
            """
            INSERT INTO tournament_types
                (code, name, short_name, calendar_code, description, is_creatable,
                 created_at, updated_at)
            VALUES
                ('month_main', 'Month Main Tournament', 'Month Main Tournament',
                 'MM', NULL, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO tournament_type_rules
                (tournament_type_id, points_multiplier, prize_place_multiplier,
                 prize_place_multiplier_places, knockout_mode, supports_bonus_points,
                 created_at, updated_at)
            SELECT id, 1.00, 1.00, NULL, 'none', 0,
                   CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            FROM tournament_types WHERE code = 'month_main'
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO tournament_economy_configs
                (tournament_type_id, entry_fee, entry_stack, addon_fee, addon_stack,
                 created_at, updated_at)
            SELECT id, 1000, 30000, 1000, 125000,
                   CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            FROM tournament_types WHERE code = 'month_main'
            """
        )
    )
    for rebuy_order, stack in ((1, 40000), (2, 50000), (3, 60000)):
        connection.execute(
            sa.text(
                """
                INSERT INTO tournament_rebuy_configs
                    (tournament_type_id, rebuy_order, fee, stack, created_at, updated_at)
                SELECT id, :rebuy_order, 1000, :stack,
                       CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                FROM tournament_types WHERE code = 'month_main'
                """
            ),
            {"rebuy_order": rebuy_order, "stack": stack},
        )


def downgrade() -> None:
    connection = op.get_bind()
    referenced = connection.execute(
        sa.text(
            """
            SELECT 1 FROM tournaments
            WHERE tournament_type_id = (
                SELECT id FROM tournament_types WHERE code = 'month_main'
            ) LIMIT 1
            """
        )
    ).first()
    if referenced:
        raise RuntimeError("Cannot downgrade: tournaments reference month_main")
    for table in (
        "tournament_rebuy_configs",
        "tournament_economy_configs",
        "tournament_type_rules",
    ):
        connection.execute(
            sa.text(
                f"""DELETE FROM {table} WHERE tournament_type_id =
                (SELECT id FROM tournament_types WHERE code = 'month_main')"""
            )
        )
    connection.execute(sa.text("DELETE FROM tournament_types WHERE code = 'month_main'"))
