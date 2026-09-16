"""prepare september 16 tournament formats

Revision ID: 7f8a9b0c1d2e
Revises: 6e7f8a9b0c1d
Create Date: 2026-09-16 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "7f8a9b0c1d2e"
down_revision: str | None = "6e7f8a9b0c1d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SLOW_BLINDS_DESCRIPTION = "Плавная структура блайндов."
SATELLITE_DESCRIPTION = (
    "Игроки, занявшие 1 и 2 место, отправляются на межклубный турнир.\nПлавная структура блайндов."
)
BLACK_PARTY_DESCRIPTION = "Тематическая вечеринка.\nВсе как в White Party."


def upgrade() -> None:
    _update_classic_v3_to_freeroll()
    _insert_plain_type(
        code="slow_blinds",
        name="Slow Blinds",
        short_name="Slow Blinds",
        calendar_code="SB",
        description=SLOW_BLINDS_DESCRIPTION,
        entry_fee=800,
        entry_stack=30_000,
        addon_fee=800,
        addon_stack=60_000,
        rebuys=((1, 800, 30_000),),
    )
    _insert_plain_type(
        code="satellite",
        name="Satellite",
        short_name="Satellite",
        calendar_code="ST",
        description=SATELLITE_DESCRIPTION,
        entry_fee=800,
        entry_stack=30_000,
        addon_fee=1000,
        addon_stack=150_000,
        rebuys=((1, 1000, 50_000), (2, 1000, 70_000)),
    )
    _insert_black_party()


def downgrade() -> None:
    _delete_types(("slow_blinds", "satellite", "black_party"))
    op.execute(
        sa.text(
            """
            UPDATE tournament_types
            SET name = 'Classic',
                short_name = 'Classic',
                calendar_code = 'C3',
                updated_at = CURRENT_TIMESTAMP
            WHERE code = 'classic_v3'
            """
        )
    )


def _update_classic_v3_to_freeroll() -> None:
    op.execute(
        sa.text(
            """
            UPDATE tournament_types
            SET name = 'Freeroll',
                short_name = 'Freeroll',
                calendar_code = 'FR',
                updated_at = CURRENT_TIMESTAMP
            WHERE code = 'classic_v3'
            """
        )
    )


def _insert_plain_type(
    *,
    code: str,
    name: str,
    short_name: str,
    calendar_code: str,
    description: str,
    entry_fee: int,
    entry_stack: int,
    addon_fee: int,
    addon_stack: int,
    rebuys: tuple[tuple[int, int, int], ...],
) -> None:
    _insert_type(
        code=code,
        name=name,
        short_name=short_name,
        calendar_code=calendar_code,
        description=description,
    )
    _insert_rule_from_values(code=code, knockout_mode="none")
    _insert_economy(
        code=code,
        entry_fee=entry_fee,
        entry_stack=entry_stack,
        addon_fee=addon_fee,
        addon_stack=addon_stack,
    )
    for rebuy_order, fee, stack in rebuys:
        _insert_rebuy(code=code, rebuy_order=rebuy_order, fee=fee, stack=stack)


def _insert_black_party() -> None:
    _insert_type(
        code="black_party",
        name="Black Party",
        short_name="Black Party",
        calendar_code="BP",
        description=BLACK_PARTY_DESCRIPTION,
    )
    _clone_rule(source_code="white_party", target_code="black_party")
    _clone_economy(source_code="white_party", target_code="black_party")
    _clone_rebuys(source_code="white_party", target_code="black_party")


def _insert_type(
    *,
    code: str,
    name: str,
    short_name: str,
    calendar_code: str,
    description: str,
) -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO tournament_types (
                code, name, short_name, calendar_code, description, is_creatable,
                created_at, updated_at
            )
            SELECT :code, :name, :short_name, :calendar_code, :description, 1,
                   CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            WHERE NOT EXISTS (SELECT 1 FROM tournament_types WHERE code = :code)
            """
        ).bindparams(
            code=code,
            name=name,
            short_name=short_name,
            calendar_code=calendar_code,
            description=description,
        )
    )


def _insert_rule_from_values(*, code: str, knockout_mode: str) -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO tournament_type_rules (
                tournament_type_id,
                points_multiplier,
                prize_place_multiplier,
                prize_place_multiplier_places,
                knockout_mode,
                supports_bonus_points,
                created_at,
                updated_at
            )
            SELECT id, 1.00, 1.00, NULL, :knockout_mode, 0,
                   CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            FROM tournament_types
            WHERE code = :code
              AND NOT EXISTS (
                  SELECT 1 FROM tournament_type_rules
                  WHERE tournament_type_id = tournament_types.id
              )
            """
        ).bindparams(code=code, knockout_mode=knockout_mode)
    )


def _clone_rule(*, source_code: str, target_code: str) -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO tournament_type_rules (
                tournament_type_id,
                points_multiplier,
                prize_place_multiplier,
                prize_place_multiplier_places,
                knockout_mode,
                supports_bonus_points,
                created_at,
                updated_at
            )
            SELECT target.id,
                   source_rule.points_multiplier,
                   source_rule.prize_place_multiplier,
                   source_rule.prize_place_multiplier_places,
                   source_rule.knockout_mode,
                   source_rule.supports_bonus_points,
                   CURRENT_TIMESTAMP,
                   CURRENT_TIMESTAMP
            FROM tournament_types AS target
            JOIN tournament_types AS source ON source.code = :source_code
            JOIN tournament_type_rules AS source_rule
                ON source_rule.tournament_type_id = source.id
            WHERE target.code = :target_code
              AND NOT EXISTS (
                  SELECT 1 FROM tournament_type_rules
                  WHERE tournament_type_id = target.id
              )
            """
        ).bindparams(source_code=source_code, target_code=target_code)
    )


def _insert_economy(
    *,
    code: str,
    entry_fee: int,
    entry_stack: int,
    addon_fee: int,
    addon_stack: int,
) -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO tournament_economy_configs (
                tournament_type_id,
                entry_fee,
                entry_stack,
                addon_fee,
                addon_stack,
                created_at,
                updated_at
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
        ).bindparams(
            code=code,
            entry_fee=entry_fee,
            entry_stack=entry_stack,
            addon_fee=addon_fee,
            addon_stack=addon_stack,
        )
    )


def _clone_economy(*, source_code: str, target_code: str) -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO tournament_economy_configs (
                tournament_type_id,
                entry_fee,
                entry_stack,
                addon_fee,
                addon_stack,
                created_at,
                updated_at
            )
            SELECT target.id,
                   source_config.entry_fee,
                   source_config.entry_stack,
                   source_config.addon_fee,
                   source_config.addon_stack,
                   CURRENT_TIMESTAMP,
                   CURRENT_TIMESTAMP
            FROM tournament_types AS target
            JOIN tournament_types AS source ON source.code = :source_code
            JOIN tournament_economy_configs AS source_config
                ON source_config.tournament_type_id = source.id
            WHERE target.code = :target_code
              AND NOT EXISTS (
                  SELECT 1 FROM tournament_economy_configs
                  WHERE tournament_type_id = target.id
              )
            """
        ).bindparams(source_code=source_code, target_code=target_code)
    )


def _insert_rebuy(*, code: str, rebuy_order: int, fee: int, stack: int) -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO tournament_rebuy_configs (
                tournament_type_id,
                rebuy_order,
                fee,
                stack,
                created_at,
                updated_at
            )
            SELECT id, :rebuy_order, :fee, :stack, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            FROM tournament_types
            WHERE code = :code
              AND NOT EXISTS (
                  SELECT 1 FROM tournament_rebuy_configs
                  WHERE tournament_type_id = tournament_types.id
                    AND rebuy_order = :rebuy_order
              )
            """
        ).bindparams(code=code, rebuy_order=rebuy_order, fee=fee, stack=stack)
    )


def _clone_rebuys(*, source_code: str, target_code: str) -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO tournament_rebuy_configs (
                tournament_type_id,
                rebuy_order,
                fee,
                stack,
                created_at,
                updated_at
            )
            SELECT target.id,
                   source_rebuy.rebuy_order,
                   source_rebuy.fee,
                   source_rebuy.stack,
                   CURRENT_TIMESTAMP,
                   CURRENT_TIMESTAMP
            FROM tournament_types AS target
            JOIN tournament_types AS source ON source.code = :source_code
            JOIN tournament_rebuy_configs AS source_rebuy
                ON source_rebuy.tournament_type_id = source.id
            WHERE target.code = :target_code
              AND NOT EXISTS (
                  SELECT 1 FROM tournament_rebuy_configs
                  WHERE tournament_type_id = target.id
                    AND rebuy_order = source_rebuy.rebuy_order
              )
            """
        ).bindparams(source_code=source_code, target_code=target_code)
    )


def _delete_types(codes: tuple[str, ...]) -> None:
    for table_name in (
        "tournament_rebuy_configs",
        "tournament_economy_configs",
        "tournament_type_rules",
    ):
        op.execute(
            sa.text(
                f"""
                DELETE FROM {table_name}
                WHERE tournament_type_id IN (
                    SELECT id FROM tournament_types WHERE code IN :codes
                )
                """
            ).bindparams(sa.bindparam("codes", expanding=True, value=codes))
        )
    op.execute(
        sa.text("DELETE FROM tournament_types WHERE code IN :codes").bindparams(
            sa.bindparam("codes", expanding=True, value=codes)
        )
    )
