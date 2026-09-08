"""add tournament scoring v2

Revision ID: 5d6e7f8a9b0c
Revises: 4c5d6e7f8a9b
Create Date: 2026-09-08 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "5d6e7f8a9b0c"
down_revision: str | None = "4c5d6e7f8a9b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

V1_CONFIG_WHERE = """
place_1_coefficient = 0.45
AND place_2_coefficient = 0.25
AND place_3_coefficient = 0.15
AND place_4_coefficient = 0.10
AND place_5_coefficient = 0.05
AND knockout_small_points = 15
AND knockout_big_points = 60
AND knockout_main_points IS NULL
AND knockout_main_final_points IS NULL
"""
V2_CONFIG_WHERE = """
place_1_coefficient = 0.45
AND place_2_coefficient = 0.30
AND place_3_coefficient = 0.20
AND place_4_coefficient = 0.15
AND place_5_coefficient = 0.10
AND knockout_small_points = 15
AND knockout_big_points = 60
AND knockout_main_points = 30
AND knockout_main_final_points = 100
"""


def upgrade() -> None:
    _add_scoring_config_v2_columns()
    _extend_knockout_mode_values()
    _add_tournament_scoring_config_fk()
    _insert_scoring_config_v2()

    v1_config_id = _required_config_id(V1_CONFIG_WHERE, "v1 scoring config")
    v2_config_id = _required_config_id(V2_CONFIG_WHERE, "v2 scoring config")

    op.execute(
        sa.text("UPDATE tournaments SET scoring_config_id = :config_id").bindparams(
            config_id=v1_config_id
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE seasons
            SET scoring_config_id = :config_id
            WHERE ends_at IS NULL
            """
        ).bindparams(config_id=v2_config_id)
    )

    _seed_tournament_types()
    _assign_previous_week_scoring_config(v2_config_id)

    with op.batch_alter_table("tournaments") as batch_op:
        batch_op.alter_column(
            "scoring_config_id",
            existing_type=sa.Integer(),
            nullable=False,
        )

    _drop_tournament_type_status()


def downgrade() -> None:
    v1_config_id = _required_config_id(V1_CONFIG_WHERE, "v1 scoring config")
    v2_config_ids = _config_ids(V2_CONFIG_WHERE)

    with op.batch_alter_table("tournament_types") as batch_op:
        batch_op.add_column(
            sa.Column(
                "status",
                sa.Enum("active", "archived", name="tournament_type_status", native_enum=False),
                nullable=True,
            )
        )
    op.execute("UPDATE tournament_types SET status = 'active'")
    with op.batch_alter_table("tournament_types") as batch_op:
        batch_op.alter_column("status", existing_type=sa.String(), nullable=False)
        batch_op.create_check_constraint(
            "tournament_types_status_values",
            "status IN ('active', 'archived')",
        )
        batch_op.create_index(op.f("ix_tournament_types_status"), ["status"])

    new_codes = ("bounty_v3", "classic_v3", "deep_stack_v2", "main_ko")
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
    op.execute(
        """
        UPDATE tournament_types
        SET is_creatable = 1
        WHERE code IN ('bounty_v2', 'classic_v2', 'deep_stack')
        """
    )

    if v2_config_ids:
        op.execute(
            sa.text(
                """
                UPDATE seasons
                SET scoring_config_id = :v1_config_id
                WHERE scoring_config_id IN :v2_config_ids
                """
            ).bindparams(
                sa.bindparam("v2_config_ids", expanding=True, value=v2_config_ids),
                v1_config_id=v1_config_id,
            )
        )

    with op.batch_alter_table("tournaments") as batch_op:
        batch_op.drop_index(op.f("ix_tournaments_scoring_config_id"))
        batch_op.drop_constraint(
            op.f("fk_tournaments_scoring_config_id_scoring_configs"),
            type_="foreignkey",
        )
        batch_op.drop_column("scoring_config_id")

    with op.batch_alter_table("tournament_type_rules") as batch_op:
        batch_op.drop_constraint("tournament_type_rules_knockout_mode_values", type_="check")
        batch_op.create_check_constraint(
            "tournament_type_rules_knockout_mode_values",
            "knockout_mode IN ('none', 'small', 'small_big')",
        )

    if v2_config_ids:
        op.execute(
            sa.text("DELETE FROM scoring_configs WHERE id IN :v2_config_ids").bindparams(
                sa.bindparam("v2_config_ids", expanding=True, value=v2_config_ids)
            )
        )

    with op.batch_alter_table("scoring_configs") as batch_op:
        batch_op.drop_constraint("knockout_main_points_nonnegative", type_="check")
        batch_op.drop_constraint("knockout_main_final_points_nonnegative", type_="check")
        batch_op.drop_column("knockout_main_points")
        batch_op.drop_column("knockout_main_final_points")
        batch_op.create_check_constraint(
            "place_coefficients_sum",
            """
            place_1_coefficient + place_2_coefficient + place_3_coefficient
            + place_4_coefficient + place_5_coefficient = 1
            """,
        )


def _add_scoring_config_v2_columns() -> None:
    with op.batch_alter_table("scoring_configs") as batch_op:
        batch_op.drop_constraint("place_coefficients_sum", type_="check")
        batch_op.add_column(sa.Column("knockout_main_points", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("knockout_main_final_points", sa.Integer(), nullable=True))
        batch_op.create_check_constraint(
            "knockout_main_points_nonnegative",
            "knockout_main_points IS NULL OR knockout_main_points >= 0",
        )
        batch_op.create_check_constraint(
            "knockout_main_final_points_nonnegative",
            "knockout_main_final_points IS NULL OR knockout_main_final_points >= 0",
        )


def _extend_knockout_mode_values() -> None:
    with op.batch_alter_table("tournament_type_rules") as batch_op:
        batch_op.drop_constraint("tournament_type_rules_knockout_mode_values", type_="check")
        batch_op.create_check_constraint(
            "tournament_type_rules_knockout_mode_values",
            "knockout_mode IN ('none', 'small', 'small_big', 'main_ko')",
        )


def _add_tournament_scoring_config_fk() -> None:
    with op.batch_alter_table("tournaments") as batch_op:
        batch_op.add_column(sa.Column("scoring_config_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            op.f("fk_tournaments_scoring_config_id_scoring_configs"),
            "scoring_configs",
            ["scoring_config_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_index(op.f("ix_tournaments_scoring_config_id"), ["scoring_config_id"])


def _insert_scoring_config_v2() -> None:
    op.execute(
        sa.text(
            f"""
            INSERT INTO scoring_configs (
                place_1_coefficient,
                place_2_coefficient,
                place_3_coefficient,
                place_4_coefficient,
                place_5_coefficient,
                knockout_small_points,
                knockout_big_points,
                knockout_main_points,
                knockout_main_final_points,
                created_at,
                updated_at
            )
            SELECT 0.45, 0.30, 0.20, 0.15, 0.10, 15, 60, 30, 100,
                   CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            WHERE NOT EXISTS (
                SELECT 1 FROM scoring_configs WHERE {V2_CONFIG_WHERE}
            )
            """
        )
    )


def _required_config_id(where_clause: str, label: str) -> int:
    result = op.get_bind().execute(
        sa.text(
            f"""
            SELECT id
            FROM scoring_configs
            WHERE {where_clause}
            ORDER BY id
            LIMIT 1
            """
        )
    )
    config_id = result.scalar_one_or_none()
    if config_id is None:
        raise RuntimeError(f"Missing {label}.")
    return int(config_id)


def _config_ids(where_clause: str) -> tuple[int, ...]:
    result = op.get_bind().execute(
        sa.text(
            f"""
            SELECT id
            FROM scoring_configs
            WHERE {where_clause}
            ORDER BY id
            """
        )
    )
    return tuple(int(config_id) for config_id in result.scalars())


def _seed_tournament_types() -> None:
    op.execute(
        """
        UPDATE tournament_types
        SET is_creatable = 0
        WHERE code IN ('bounty_v2', 'classic_v2', 'deep_stack')
        """
    )
    _insert_type(
        code="bounty_v3",
        name="Bounty",
        short_name="Bounty",
        description=(
            "Динамические нокауты: до финального стола малые КО, на финальном столе большие КО."
        ),
        source_code="bounty_v2",
        knockout_mode="small_big",
        entry_fee=600,
        entry_stack=20_000,
        addon_fee=800,
        addon_stack=125_000,
        rebuys=(
            (1, 800, 30_000),
            (2, 800, 50_000),
            (3, 800, 60_000),
            (4, 1000, 80_000),
            (5, 1000, 80_000),
        ),
    )
    _insert_type(
        code="classic_v3",
        name="Classic",
        short_name="Classic",
        description=(
            "Классический турнир. Комбо-бонусы выплачиваются фишками "
            "во время игры и не влияют на рейтинг."
        ),
        source_code="classic_v2",
        knockout_mode="none",
        entry_fee=0,
        entry_stack=15_000,
        addon_fee=800,
        addon_stack=125_000,
        rebuys=(
            (1, 800, 30_000),
            (2, 800, 50_000),
            (3, 800, 60_000),
            (4, 1000, 80_000),
            (5, 1000, 80_000),
        ),
    )
    _insert_type(
        code="deep_stack_v2",
        name="Deep Stack",
        short_name="Deep Stack",
        description="Гарантированный фонд турнира — 2500 очков.",
        source_code="deep_stack",
        knockout_mode="none",
        entry_fee=800,
        entry_stack=40_000,
        addon_fee=800,
        addon_stack=150_000,
        rebuys=(
            (1, 800, 50_000),
            (2, 800, 70_000),
            (3, 1000, 90_000),
            (4, 1000, 90_000),
            (5, 1000, 100_000),
        ),
    )
    _insert_type(
        code="main_ko",
        name="MAIN KO",
        short_name="MAIN KO",
        description="MAIN KO: увеличенные нокауты до финального стола и на финальном столе.",
        source_code=None,
        knockout_mode="main_ko",
        entry_fee=800,
        entry_stack=30_000,
        addon_fee=1000,
        addon_stack=150_000,
        rebuys=((1, 1000, 40_000), (2, 1000, 60_000)),
    )


def _insert_type(
    *,
    code: str,
    name: str,
    short_name: str,
    description: str,
    source_code: str | None,
    knockout_mode: str,
    entry_fee: int,
    entry_stack: int,
    addon_fee: int,
    addon_stack: int,
    rebuys: tuple[tuple[int, int, int], ...],
) -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO tournament_types (
                code, name, short_name, description, status, is_creatable,
                created_at, updated_at
            )
            SELECT :code, :name, :short_name, :description, 'active', 1,
                   CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            WHERE NOT EXISTS (SELECT 1 FROM tournament_types WHERE code = :code)
            """
        ).bindparams(
            code=code,
            name=name,
            short_name=short_name,
            description=description,
        )
    )
    _insert_rule(code=code, source_code=source_code, knockout_mode=knockout_mode)
    _insert_economy(
        code=code,
        entry_fee=entry_fee,
        entry_stack=entry_stack,
        addon_fee=addon_fee,
        addon_stack=addon_stack,
    )
    for rebuy_order, fee, stack in rebuys:
        _insert_rebuy(code=code, rebuy_order=rebuy_order, fee=fee, stack=stack)


def _insert_rule(*, code: str, source_code: str | None, knockout_mode: str) -> None:
    if source_code is None:
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
        return
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
                   :knockout_mode,
                   source_rule.supports_bonus_points,
                   CURRENT_TIMESTAMP,
                   CURRENT_TIMESTAMP
            FROM tournament_types AS target
            JOIN tournament_types AS source_type ON source_type.code = :source_code
            JOIN tournament_type_rules AS source_rule
                ON source_rule.tournament_type_id = source_type.id
            WHERE target.code = :code
              AND NOT EXISTS (
                  SELECT 1 FROM tournament_type_rules
                  WHERE tournament_type_id = target.id
              )
            """
        ).bindparams(code=code, source_code=source_code, knockout_mode=knockout_mode)
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


def _assign_previous_week_scoring_config(v2_config_id: int) -> None:
    op.execute(
        sa.text(
            """
            UPDATE tournaments
            SET scoring_config_id = :scoring_config_id
            WHERE date IN (
                '2026-09-02',
                '2026-09-03',
                '2026-09-04',
                '2026-09-05',
                '2026-09-06'
            )
            """
        ).bindparams(scoring_config_id=v2_config_id)
    )


def _drop_tournament_type_status() -> None:
    op.drop_index(op.f("ix_tournament_types_status"), table_name="tournament_types")
    with op.batch_alter_table("tournament_types") as batch_op:
        batch_op.drop_constraint("tournament_types_status_values", type_="check")
        batch_op.drop_column("status")
