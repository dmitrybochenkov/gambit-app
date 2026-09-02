"""add versioned tournament formats

Revision ID: 4c5d6e7f8a9b
Revises: 3b4c5d6e7f8a
Create Date: 2026-09-02 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "4c5d6e7f8a9b"
down_revision: str | None = "3b4c5d6e7f8a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HISTORICAL_CODES = (
    "bounty",
    "classic",
    "freezeout",
    "double_double",
    "legacy_unknown",
)
CREATABLE_EXISTING_CODES = ("mystery_bounty", "boss_bounty")

NEW_TYPES = (
    (
        "bounty_v2",
        "Bounty",
        "Bounty",
        "bounty",
        "Динамические нокауты: до финального стола малые КО, на финальном столе большие КО.",
    ),
    (
        "classic_v2",
        "Classic",
        "Classic",
        "classic",
        "Классический турнир. Комбо-бонусы выплачиваются фишками "
        "во время игры и не влияют на рейтинг.",
    ),
    (
        "freezeout_v2",
        "Freezeout",
        "Freezeout",
        "freezeout",
        "Формат для скилловых игроков. Рейтинг за 1 и 2 место умножается на 1.5.\n"
        "На этот турнир не действуют привилегии клуба.",
    ),
    (
        "deep_stack",
        "Deep Stack",
        "Deep Stack",
        "double_double",
        "Гарантированный фонд турнира — 2500 очков.",
    ),
)

WHITE_PARTY_REBUYS = (
    (1, 800, 40_000),
    (2, 800, 50_000),
    (3, 1000, 80_000),
    (4, 1000, 100_000),
)


def upgrade() -> None:
    with op.batch_alter_table("tournament_types") as batch_op:
        batch_op.add_column(sa.Column("is_creatable", sa.Boolean(), nullable=True))
        batch_op.create_index(
            op.f("ix_tournament_types_is_creatable"),
            ["is_creatable"],
        )

    op.execute("UPDATE tournament_types SET is_creatable = 0")
    for code in CREATABLE_EXISTING_CODES:
        op.execute(
            sa.text(
                """
                UPDATE tournament_types
                SET is_creatable = 1
                WHERE code = :code
                """
            ).bindparams(code=code)
        )

    for new_code, name, short_name, source_code, description in NEW_TYPES:
        _insert_type_from_source(
            new_code=new_code,
            name=name,
            short_name=short_name,
            source_code=source_code,
            description=description,
        )
        _copy_rule(new_code=new_code, source_code=source_code)
        _copy_economy(new_code=new_code, source_code=source_code)
        _copy_rebuys(new_code=new_code, source_code=source_code)

    _insert_white_party()

    _update_bounty_v2_first_rebuy()
    _update_classic_v2_economy()
    _update_deep_stack_rule()
    _update_weekly_templates()

    for code in HISTORICAL_CODES:
        op.execute(
            sa.text(
                """
                UPDATE tournament_types
                SET is_creatable = 0
                WHERE code = :code
                """
            ).bindparams(code=code)
        )

    with op.batch_alter_table("tournament_types") as batch_op:
        batch_op.alter_column(
            "is_creatable",
            existing_type=sa.Boolean(),
            nullable=False,
        )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE weekly_tournament_templates
            SET tournament_type_id = (
                SELECT id FROM tournament_types WHERE code = 'bounty'
            )
            WHERE weekday = 2
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE weekly_tournament_templates
            SET tournament_type_id = (
                SELECT id FROM tournament_types WHERE code = 'classic'
            )
            WHERE weekday = 3
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE weekly_tournament_templates
            SET tournament_type_id = (
                SELECT id FROM tournament_types WHERE code = 'freezeout'
            )
            WHERE weekday = 4
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE weekly_tournament_templates
            SET tournament_type_id = (
                SELECT id FROM tournament_types WHERE code = 'double_double'
            )
            WHERE weekday = 5
            """
        )
    )

    new_codes = ("bounty_v2", "classic_v2", "freezeout_v2", "deep_stack", "white_party")
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
            ).bindparams(sa.bindparam("codes", expanding=True, value=new_codes))
        )
    op.execute(
        sa.text("DELETE FROM tournament_types WHERE code IN :codes").bindparams(
            sa.bindparam("codes", expanding=True, value=new_codes)
        )
    )

    with op.batch_alter_table("tournament_types") as batch_op:
        batch_op.drop_index(op.f("ix_tournament_types_is_creatable"))
        batch_op.drop_column("is_creatable")


def _insert_type_from_source(
    *,
    new_code: str,
    name: str,
    short_name: str,
    source_code: str,
    description: str,
) -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO tournament_types (
                code, name, short_name, description, status, is_creatable,
                created_at, updated_at
            )
            SELECT
                :new_code,
                :name,
                :short_name,
                :description,
                source.status,
                1,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            FROM tournament_types AS source
            WHERE source.code = :source_code
              AND NOT EXISTS (
                  SELECT 1 FROM tournament_types WHERE code = :new_code
              )
            """
        ).bindparams(
            new_code=new_code,
            name=name,
            short_name=short_name,
            description=description,
            source_code=source_code,
        )
    )


def _copy_rule(*, new_code: str, source_code: str) -> None:
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
            SELECT
                target.id,
                source_rule.points_multiplier,
                source_rule.prize_place_multiplier,
                source_rule.prize_place_multiplier_places,
                source_rule.knockout_mode,
                source_rule.supports_bonus_points,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            FROM tournament_types AS target
            JOIN tournament_types AS source_type ON source_type.code = :source_code
            JOIN tournament_type_rules AS source_rule
                ON source_rule.tournament_type_id = source_type.id
            WHERE target.code = :new_code
              AND NOT EXISTS (
                  SELECT 1
                  FROM tournament_type_rules
                  WHERE tournament_type_id = target.id
              )
            """
        ).bindparams(new_code=new_code, source_code=source_code)
    )


def _copy_economy(*, new_code: str, source_code: str) -> None:
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
            SELECT
                target.id,
                source_economy.entry_fee,
                source_economy.entry_stack,
                source_economy.addon_fee,
                source_economy.addon_stack,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            FROM tournament_types AS target
            JOIN tournament_types AS source_type ON source_type.code = :source_code
            JOIN tournament_economy_configs AS source_economy
                ON source_economy.tournament_type_id = source_type.id
            WHERE target.code = :new_code
              AND NOT EXISTS (
                  SELECT 1
                  FROM tournament_economy_configs
                  WHERE tournament_type_id = target.id
              )
            """
        ).bindparams(new_code=new_code, source_code=source_code)
    )


def _copy_rebuys(*, new_code: str, source_code: str) -> None:
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
            SELECT
                target.id,
                source_rebuy.rebuy_order,
                source_rebuy.fee,
                source_rebuy.stack,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            FROM tournament_types AS target
            JOIN tournament_types AS source_type ON source_type.code = :source_code
            JOIN tournament_rebuy_configs AS source_rebuy
                ON source_rebuy.tournament_type_id = source_type.id
            WHERE target.code = :new_code
              AND NOT EXISTS (
                  SELECT 1
                  FROM tournament_rebuy_configs
                  WHERE tournament_type_id = target.id
              )
            """
        ).bindparams(new_code=new_code, source_code=source_code)
    )


def _insert_white_party() -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO tournament_types (
                code, name, short_name, description, status, is_creatable,
                created_at, updated_at
            )
            SELECT
                'white_party',
                'White Party Tournament',
                'White Party',
                'Приди в белом — получи фишки к стеку.' || char(10) ||
                    'Приди в тёмных очках — получи фишки к стеку.',
                'active',
                1,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            WHERE NOT EXISTS (
                SELECT 1 FROM tournament_types WHERE code = 'white_party'
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
                supports_bonus_points,
                created_at,
                updated_at
            )
            SELECT id, 1.00, 1.00, NULL, 'none', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            FROM tournament_types
            WHERE code = 'white_party'
              AND NOT EXISTS (
                  SELECT 1
                  FROM tournament_type_rules
                  WHERE tournament_type_id = tournament_types.id
              )
            """
        )
    )
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
            SELECT id, 800, 30000, 1000, 150000, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            FROM tournament_types
            WHERE code = 'white_party'
              AND NOT EXISTS (
                  SELECT 1
                  FROM tournament_economy_configs
                  WHERE tournament_type_id = tournament_types.id
              )
            """
        )
    )
    for rebuy_order, fee, stack in WHITE_PARTY_REBUYS:
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
                WHERE code = 'white_party'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM tournament_rebuy_configs
                      WHERE tournament_type_id = tournament_types.id
                        AND rebuy_order = :rebuy_order
                  )
                """
            ).bindparams(rebuy_order=rebuy_order, fee=fee, stack=stack)
        )


def _update_bounty_v2_first_rebuy() -> None:
    op.execute(
        sa.text(
            """
            UPDATE tournament_rebuy_configs
            SET fee = 800
            WHERE rebuy_order = 1
              AND tournament_type_id = (
                  SELECT id FROM tournament_types WHERE code = 'bounty_v2'
              )
            """
        )
    )


def _update_classic_v2_economy() -> None:
    op.execute(
        sa.text(
            """
            UPDATE tournament_economy_configs
            SET entry_fee = 600
            WHERE tournament_type_id = (
                SELECT id FROM tournament_types WHERE code = 'classic_v2'
            )
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE tournament_rebuy_configs
            SET fee = 800
            WHERE rebuy_order = 1
              AND tournament_type_id = (
                  SELECT id FROM tournament_types WHERE code = 'classic_v2'
              )
            """
        )
    )


def _update_deep_stack_rule() -> None:
    op.execute(
        sa.text(
            """
            UPDATE tournament_type_rules
            SET points_multiplier = 1.00
            WHERE tournament_type_id = (
                SELECT id FROM tournament_types WHERE code = 'deep_stack'
            )
            """
        )
    )


def _update_weekly_templates() -> None:
    for weekday, code in (
        (2, "bounty_v2"),
        (3, "classic_v2"),
        (4, "freezeout_v2"),
        (5, "deep_stack"),
    ):
        op.execute(
            sa.text(
                """
                UPDATE weekly_tournament_templates
                SET tournament_type_id = (
                    SELECT id FROM tournament_types WHERE code = :code
                )
                WHERE weekday = :weekday
                  AND rotation_order IS NULL
                """
            ).bindparams(weekday=weekday, code=code)
        )
