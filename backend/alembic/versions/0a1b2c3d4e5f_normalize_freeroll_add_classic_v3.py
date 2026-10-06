"""Normalize Freeroll identity and add Classic v3.

Revision ID: 0a1b2c3d4e5f
Revises: f6a7b8c9d0e2
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0a1b2c3d4e5f"
down_revision: str | None = "f6a7b8c9d0e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    if connection.execute(
        sa.text("SELECT COUNT(*) FROM tournament_types WHERE code = 'freeroll'")
    ).scalar_one():
        raise RuntimeError("Tournament type code 'freeroll' already exists")

    freeroll = connection.execute(
        sa.text(
            """
            SELECT id, name, short_name, calendar_code
            FROM tournament_types
            WHERE code = 'classic_v3'
            """
        )
    ).one_or_none()
    if freeroll is None or tuple(freeroll[1:]) != ("Freeroll", "Freeroll", "FR"):
        raise RuntimeError("Expected classic_v3 to be the existing Freeroll format")

    classic_v2_id = connection.execute(
        sa.text("SELECT id FROM tournament_types WHERE code = 'classic_v2'")
    ).scalar_one_or_none()
    if classic_v2_id is None:
        raise RuntimeError("Required tournament type 'classic_v2' is missing")

    connection.execute(
        sa.text("UPDATE tournament_types SET code = 'freeroll' WHERE id = :id"),
        {"id": freeroll.id},
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO tournament_types (
                code, name, short_name, calendar_code, description, is_creatable,
                created_at, updated_at
            )
            SELECT
                'classic_v3', 'Классика 3', 'Классика 3', 'C3', description, 1,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            FROM tournament_types
            WHERE id = :classic_v2_id
            """
        ),
        {"classic_v2_id": classic_v2_id},
    )
    if (
        connection.execute(
            sa.text("SELECT COUNT(*) FROM tournament_types WHERE code = 'classic_v3'")
        ).scalar_one()
        != 1
    ):
        raise RuntimeError("Failed to create exactly one Classic v3 tournament type")
    _copy_configuration(connection, classic_v2_id)


def downgrade() -> None:
    connection = op.get_bind()
    classic_v3_id = connection.execute(
        sa.text("SELECT id FROM tournament_types WHERE code = 'classic_v3'")
    ).scalar_one_or_none()
    freeroll_id = connection.execute(
        sa.text("SELECT id FROM tournament_types WHERE code = 'freeroll'")
    ).scalar_one_or_none()
    if classic_v3_id is None or freeroll_id is None:
        raise RuntimeError("Expected classic_v3 and freeroll tournament types")

    references = connection.execute(
        sa.text(
            """
            SELECT
                (SELECT COUNT(*) FROM tournaments WHERE tournament_type_id = :type_id)
                + (SELECT COUNT(*) FROM weekly_tournament_templates
                   WHERE tournament_type_id = :type_id)
            """
        ),
        {"type_id": classic_v3_id},
    ).scalar_one()
    if references:
        raise RuntimeError("Cannot downgrade while Classic v3 is referenced")

    for table_name in (
        "tournament_rebuy_configs",
        "tournament_economy_configs",
        "tournament_type_rules",
    ):
        connection.execute(
            sa.text(f"DELETE FROM {table_name} WHERE tournament_type_id = :id"),
            {"id": classic_v3_id},
        )
    connection.execute(
        sa.text("DELETE FROM tournament_types WHERE id = :id"),
        {"id": classic_v3_id},
    )
    connection.execute(
        sa.text("UPDATE tournament_types SET code = 'classic_v3' WHERE id = :id"),
        {"id": freeroll_id},
    )


def _copy_configuration(connection: sa.Connection, classic_v2_id: int) -> None:
    classic_v3_id = connection.execute(
        sa.text("SELECT id FROM tournament_types WHERE code = 'classic_v3'")
    ).scalar_one()
    connection.execute(
        sa.text(
            """
            INSERT INTO tournament_type_rules (
                tournament_type_id, points_multiplier, prize_place_multiplier,
                prize_place_multiplier_places, knockout_mode, supports_bonus_points,
                created_at, updated_at
            )
            SELECT
                :target_id, points_multiplier, prize_place_multiplier,
                prize_place_multiplier_places, knockout_mode, supports_bonus_points,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            FROM tournament_type_rules
            WHERE tournament_type_id = :source_id
            """
        ),
        {"target_id": classic_v3_id, "source_id": classic_v2_id},
    )
    if _configuration_count(connection, "tournament_type_rules", classic_v3_id) != 1:
        raise RuntimeError("Classic v2 must have exactly one rules row")
    connection.execute(
        sa.text(
            """
            INSERT INTO tournament_economy_configs (
                tournament_type_id, entry_fee, entry_stack, addon_fee, addon_stack,
                created_at, updated_at
            )
            SELECT
                :target_id, 800, entry_stack, addon_fee, addon_stack,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            FROM tournament_economy_configs
            WHERE tournament_type_id = :source_id
            """
        ),
        {"target_id": classic_v3_id, "source_id": classic_v2_id},
    )
    if _configuration_count(connection, "tournament_economy_configs", classic_v3_id) != 1:
        raise RuntimeError("Classic v2 must have exactly one economy row")
    source_rebuy_count = connection.execute(
        sa.text(
            "SELECT COUNT(*) FROM tournament_rebuy_configs WHERE tournament_type_id = :source_id"
        ),
        {"source_id": classic_v2_id},
    ).scalar_one()
    connection.execute(
        sa.text(
            """
            INSERT INTO tournament_rebuy_configs (
                tournament_type_id, rebuy_order, fee, stack, created_at, updated_at
            )
            SELECT
                :target_id, rebuy_order, fee, stack, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            FROM tournament_rebuy_configs
            WHERE tournament_type_id = :source_id
            ORDER BY rebuy_order
            """
        ),
        {"target_id": classic_v3_id, "source_id": classic_v2_id},
    )
    if (
        source_rebuy_count == 0
        or _configuration_count(connection, "tournament_rebuy_configs", classic_v3_id)
        != source_rebuy_count
    ):
        raise RuntimeError("Failed to copy the complete Classic v2 rebuy configuration")


def _configuration_count(connection: sa.Connection, table_name: str, type_id: int) -> int:
    return connection.execute(
        sa.text(f"SELECT COUNT(*) FROM {table_name} WHERE tournament_type_id = :id"),
        {"id": type_id},
    ).scalar_one()
