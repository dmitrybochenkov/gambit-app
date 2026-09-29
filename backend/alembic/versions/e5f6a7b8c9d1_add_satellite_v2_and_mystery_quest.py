"""add Satellite v2 and Mystery Quest tournament types

Revision ID: e5f6a7b8c9d1
Revises: d4e5f6a7b8c9
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e5f6a7b8c9d1"
down_revision: str | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    targets = (
        {
            "code": "satellite_v2",
            "name": "Satellite",
            "short_name": "Satellite",
            "calendar_code": "S2",
            "description_source_code": "satellite",
            "entry_fee": 1000,
            "entry_stack": 30_000,
            "addon_fee": 1000,
            "addon_stack": 125_000,
            "rebuys": ((1, 1000, 40_000), (2, 1000, 50_000), (3, 1000, 70_000)),
            "supports_bonus_points": False,
        },
        {
            "code": "mystery_quest",
            "name": "Mystery Quest",
            "short_name": "Mystery Quest",
            "calendar_code": "MQ",
            "description_source_code": None,
            "entry_fee": 800,
            "entry_stack": 20_000,
            "addon_fee": 800,
            "addon_stack": 125_000,
            "rebuys": (
                (1, 800, 30_000),
                (2, 800, 50_000),
                (3, 800, 60_000),
                (4, 1000, 80_000),
                (5, 1000, 80_000),
            ),
            "supports_bonus_points": True,
        },
    )
    for target in targets:
        _validate_target_if_present(connection, **target)
    for target in targets:
        _insert_target(connection, **target)
        _validate_target(connection, **target)

    connection.execute(
        sa.text(
            """
            UPDATE tournament_types
            SET calendar_code = 'S1', is_creatable = 0, updated_at = CURRENT_TIMESTAMP
            WHERE code = 'satellite'
            """
        )
    )
    connection.execute(
        sa.text(
            """
            UPDATE weekly_tournament_templates
            SET tournament_type_id = (
                    SELECT id FROM tournament_types WHERE code = 'satellite_v2'
                ),
                updated_at = CURRENT_TIMESTAMP
            WHERE is_active = 1
              AND tournament_type_id = (
                  SELECT id FROM tournament_types WHERE code = 'satellite'
              )
            """
        )
    )


def _insert_target(
    connection: sa.Connection,
    *,
    code: str,
    name: str,
    short_name: str,
    calendar_code: str,
    description_source_code: str | None,
    entry_fee: int,
    entry_stack: int,
    addon_fee: int,
    addon_stack: int,
    rebuys: tuple[tuple[int, int, int], ...],
    supports_bonus_points: bool,
) -> None:
    _insert_type(
        connection,
        code=code,
        name=name,
        short_name=short_name,
        calendar_code=calendar_code,
        description_source_code=description_source_code,
    )
    _insert_config(
        connection,
        code=code,
        entry_fee=entry_fee,
        entry_stack=entry_stack,
        addon_fee=addon_fee,
        addon_stack=addon_stack,
        rebuys=rebuys,
        supports_bonus_points=supports_bonus_points,
    )


def _validate_target_if_present(connection: sa.Connection, **target: object) -> None:
    code = str(target["code"])
    exists = connection.execute(
        sa.text("SELECT 1 FROM tournament_types WHERE code = :code"),
        {"code": code},
    ).first()
    if exists is not None:
        _validate_target(connection, **target)


def _validate_target(
    connection: sa.Connection,
    *,
    code: str,
    name: str,
    short_name: str,
    calendar_code: str,
    description_source_code: str | None,
    entry_fee: int,
    entry_stack: int,
    addon_fee: int,
    addon_stack: int,
    rebuys: tuple[tuple[int, int, int], ...],
    supports_bonus_points: bool,
) -> None:
    expected_description = connection.execute(
        sa.text("SELECT description FROM tournament_types WHERE code = :code"),
        {"code": description_source_code},
    ).scalar_one_or_none()
    type_row = connection.execute(
        sa.text(
            """
            SELECT name, short_name, calendar_code, description, is_creatable
            FROM tournament_types WHERE code = :code
            """
        ),
        {"code": code},
    ).one_or_none()
    expected_type = (name, short_name, calendar_code, expected_description, 1)
    economy_rows = connection.execute(
        sa.text(
            """
            SELECT entry_fee, entry_stack, addon_fee, addon_stack
            FROM tournament_economy_configs
            WHERE tournament_type_id = (SELECT id FROM tournament_types WHERE code = :code)
            """
        ),
        {"code": code},
    ).all()
    rule_rows = connection.execute(
        sa.text(
            """
            SELECT points_multiplier, prize_place_multiplier,
                   prize_place_multiplier_places, knockout_mode, supports_bonus_points
            FROM tournament_type_rules
            WHERE tournament_type_id = (SELECT id FROM tournament_types WHERE code = :code)
            """
        ),
        {"code": code},
    ).all()
    rebuy_rows = connection.execute(
        sa.text(
            """
            SELECT rebuy_order, fee, stack
            FROM tournament_rebuy_configs
            WHERE tournament_type_id = (SELECT id FROM tournament_types WHERE code = :code)
            ORDER BY rebuy_order, id
            """
        ),
        {"code": code},
    ).all()
    valid = (
        type_row is not None
        and tuple(type_row) == expected_type
        and [tuple(row) for row in economy_rows]
        == [(entry_fee, entry_stack, addon_fee, addon_stack)]
        and [tuple(row) for row in rule_rows] == [(1, 1, None, "none", int(supports_bonus_points))]
        and [tuple(row) for row in rebuy_rows] == list(rebuys)
    )
    if not valid:
        raise RuntimeError(f"Conflicting or incomplete tournament type configuration: {code}")


def downgrade() -> None:
    connection = op.get_bind()
    referenced = connection.execute(
        sa.text(
            """
            SELECT code
            FROM tournament_types
            WHERE code IN ('satellite_v2', 'mystery_quest')
              AND id IN (SELECT tournament_type_id FROM tournaments)
            LIMIT 1
            """
        )
    ).first()
    if referenced:
        raise RuntimeError(f"Cannot downgrade: tournaments reference {referenced[0]}")

    connection.execute(
        sa.text(
            """
            UPDATE weekly_tournament_templates
            SET tournament_type_id = (
                    SELECT id FROM tournament_types WHERE code = 'satellite'
                ),
                updated_at = CURRENT_TIMESTAMP
            WHERE is_active = 1
              AND tournament_type_id = (
                  SELECT id FROM tournament_types WHERE code = 'satellite_v2'
              )
            """
        )
    )
    for code in ("satellite_v2", "mystery_quest"):
        _delete_type(connection, code)
    connection.execute(
        sa.text(
            """
            UPDATE tournament_types
            SET calendar_code = 'ST', is_creatable = 1, updated_at = CURRENT_TIMESTAMP
            WHERE code = 'satellite'
            """
        )
    )


def _insert_type(
    connection: sa.Connection,
    *,
    code: str,
    name: str,
    short_name: str,
    calendar_code: str,
    description_source_code: str | None,
) -> None:
    connection.execute(
        sa.text(
            """
            INSERT INTO tournament_types (
                code, name, short_name, calendar_code, description, is_creatable,
                created_at, updated_at
            )
            SELECT :code, :name, :short_name, :calendar_code,
                   source.description, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            FROM (SELECT 1) AS seed
            LEFT JOIN tournament_types AS source ON source.code = :description_source_code
            WHERE NOT EXISTS (SELECT 1 FROM tournament_types WHERE code = :code)
            """
        ),
        {
            "code": code,
            "name": name,
            "short_name": short_name,
            "calendar_code": calendar_code,
            "description_source_code": description_source_code,
        },
    )


def _insert_config(
    connection: sa.Connection,
    *,
    code: str,
    entry_fee: int,
    entry_stack: int,
    addon_fee: int,
    addon_stack: int,
    rebuys: tuple[tuple[int, int, int], ...],
    supports_bonus_points: bool,
) -> None:
    connection.execute(
        sa.text(
            """
            INSERT INTO tournament_type_rules (
                tournament_type_id, points_multiplier, prize_place_multiplier,
                prize_place_multiplier_places, knockout_mode, supports_bonus_points,
                created_at, updated_at
            )
            SELECT id, 1.00, 1.00, NULL, 'none', :supports_bonus_points,
                   CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            FROM tournament_types
            WHERE code = :code
              AND NOT EXISTS (
                  SELECT 1 FROM tournament_type_rules
                  WHERE tournament_type_id = tournament_types.id
              )
            """
        ),
        {"code": code, "supports_bonus_points": int(supports_bonus_points)},
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO tournament_economy_configs (
                tournament_type_id, entry_fee, entry_stack, addon_fee, addon_stack,
                created_at, updated_at
            )
            SELECT id, :entry_fee, :entry_stack, :addon_fee, :addon_stack,
                   CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            FROM tournament_types
            WHERE code = :code
              AND NOT EXISTS (
                  SELECT 1 FROM tournament_economy_configs
                  WHERE tournament_type_id = tournament_types.id
              )
            """
        ),
        {
            "code": code,
            "entry_fee": entry_fee,
            "entry_stack": entry_stack,
            "addon_fee": addon_fee,
            "addon_stack": addon_stack,
        },
    )
    for rebuy_order, fee, stack in rebuys:
        connection.execute(
            sa.text(
                """
                INSERT INTO tournament_rebuy_configs (
                    tournament_type_id, rebuy_order, fee, stack, created_at, updated_at
                )
                SELECT id, :rebuy_order, :fee, :stack,
                       CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                FROM tournament_types
                WHERE code = :code
                  AND NOT EXISTS (
                      SELECT 1 FROM tournament_rebuy_configs
                      WHERE tournament_type_id = tournament_types.id
                        AND rebuy_order = :rebuy_order
                  )
                """
            ),
            {"code": code, "rebuy_order": rebuy_order, "fee": fee, "stack": stack},
        )


def _delete_type(connection: sa.Connection, code: str) -> None:
    for table in (
        "tournament_rebuy_configs",
        "tournament_economy_configs",
        "tournament_type_rules",
    ):
        connection.execute(
            sa.text(
                f"""DELETE FROM {table} WHERE tournament_type_id =
                (SELECT id FROM tournament_types WHERE code = :code)"""
            ),
            {"code": code},
        )
    connection.execute(sa.text("DELETE FROM tournament_types WHERE code = :code"), {"code": code})
