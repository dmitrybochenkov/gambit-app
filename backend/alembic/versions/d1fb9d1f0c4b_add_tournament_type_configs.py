"""add tournament type configs

Revision ID: d1fb9d1f0c4b
Revises: 8f0b8dd4f4d2
Create Date: 2026-07-12 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d1fb9d1f0c4b"
down_revision: str | None = "8f0b8dd4f4d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TOURNAMENT_TYPES = [
    (
        "bounty",
        "Баунти турнир",
        "Динамические нокауты: до финального стола малые КО, на финальном столе большие КО.",
    ),
    (
        "classic",
        "Классика",
        "Классический турнир. Комбо-бонусы выплачиваются фишками "
        "во время игры и не влияют на рейтинг.",
    ),
    (
        "freezeout",
        "Фризаут",
        "Формат для скилловых игроков. Рейтинг за 1 и 2 место умножается на 1.5.",
    ),
    ("double_double", "Double Double", "Удвоенный рейтинг и увеличенные стеки."),
    ("mystery_bounty", "Mystery Bounty", "Воскресный bounty-формат с mystery-наградами."),
    ("boss_bounty", "Boss Bounty", "Воскресный bounty-формат: обычные КО малые, КО босса большие."),
]

RULES = {
    "bounty": ("1.00", "1.00", None, "small_big"),
    "classic": ("1.00", "1.00", None, "none"),
    "freezeout": ("1.00", "1.50", "[1,2]", "none"),
    "double_double": ("2.00", "1.00", None, "none"),
    "mystery_bounty": ("1.00", "1.00", None, "small"),
    "boss_bounty": ("1.00", "1.00", None, "small_big"),
}

STANDARD_ECONOMY_CODES = {"bounty", "classic", "mystery_bounty", "boss_bounty"}
STANDARD_REBUYS = [
    (1, 600, 30_000),
    (2, 800, 50_000),
    (3, 800, 70_000),
    (4, 800, 90_000),
    (5, 1000, 100_000),
    (6, 1000, 100_000),
]
DOUBLE_DOUBLE_REBUYS = [
    (1, 800, 60_000),
    (2, 800, 80_000),
    (3, 800, 80_000),
    (4, 1000, 100_000),
    (5, 1000, 100_000),
]
WEEKLY_TEMPLATES = [
    (2, "bounty", None),
    (3, "classic", None),
    (4, "freezeout", None),
    (5, "double_double", None),
    (6, "mystery_bounty", 1),
    (6, "boss_bounty", 2),
]


def upgrade() -> None:
    op.create_table(
        "tournament_types",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("active", "archived", name="tournament_type_status", native_enum=False),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tournament_types")),
        sa.UniqueConstraint("code", name=op.f("uq_tournament_types_code")),
    )
    op.create_index(op.f("ix_tournament_types_status"), "tournament_types", ["status"])

    op.create_table(
        "tournament_type_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tournament_type_id", sa.Integer(), nullable=False),
        sa.Column("points_multiplier", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("prize_place_multiplier", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("prize_place_multiplier_places", sa.Text(), nullable=True),
        sa.Column(
            "knockout_mode",
            sa.Enum("none", "small", "small_big", name="knockout_mode", native_enum=False),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "points_multiplier > 0",
            name=op.f("ck_tournament_type_rules_points_multiplier_positive"),
        ),
        sa.CheckConstraint(
            "prize_place_multiplier > 0",
            name=op.f("ck_tournament_type_rules_prize_place_multiplier_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["tournament_type_id"],
            ["tournament_types.id"],
            name=op.f("fk_tournament_type_rules_tournament_type_id_tournament_types"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tournament_type_rules")),
        sa.UniqueConstraint(
            "tournament_type_id",
            name=op.f("uq_tournament_type_rules_tournament_type_id"),
        ),
    )
    op.create_index(
        op.f("ix_tournament_type_rules_tournament_type_id"),
        "tournament_type_rules",
        ["tournament_type_id"],
    )

    op.create_table(
        "tournament_economy_configs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tournament_type_id", sa.Integer(), nullable=False),
        sa.Column("entry_fee", sa.Integer(), nullable=False),
        sa.Column("entry_stack", sa.Integer(), nullable=False),
        sa.Column("addon_fee", sa.Integer(), nullable=False),
        sa.Column("addon_stack", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "entry_fee >= 0",
            name=op.f("ck_tournament_economy_configs_entry_fee_nonnegative"),
        ),
        sa.CheckConstraint(
            "entry_stack > 0",
            name=op.f("ck_tournament_economy_configs_entry_stack_positive"),
        ),
        sa.CheckConstraint(
            "addon_fee >= 0",
            name=op.f("ck_tournament_economy_configs_addon_fee_nonnegative"),
        ),
        sa.CheckConstraint(
            "addon_stack > 0",
            name=op.f("ck_tournament_economy_configs_addon_stack_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["tournament_type_id"],
            ["tournament_types.id"],
            name=op.f("fk_tournament_economy_configs_tournament_type_id_tournament_types"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tournament_economy_configs")),
        sa.UniqueConstraint(
            "tournament_type_id",
            name=op.f("uq_tournament_economy_configs_tournament_type_id"),
        ),
    )
    op.create_index(
        op.f("ix_tournament_economy_configs_tournament_type_id"),
        "tournament_economy_configs",
        ["tournament_type_id"],
    )

    op.create_table(
        "tournament_rebuy_configs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tournament_type_id", sa.Integer(), nullable=False),
        sa.Column("rebuy_order", sa.Integer(), nullable=False),
        sa.Column("fee", sa.Integer(), nullable=False),
        sa.Column("stack", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "rebuy_order > 0",
            name=op.f("ck_tournament_rebuy_configs_rebuy_order_positive"),
        ),
        sa.CheckConstraint(
            "fee >= 0",
            name=op.f("ck_tournament_rebuy_configs_fee_nonnegative"),
        ),
        sa.CheckConstraint(
            "stack > 0",
            name=op.f("ck_tournament_rebuy_configs_stack_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["tournament_type_id"],
            ["tournament_types.id"],
            name=op.f("fk_tournament_rebuy_configs_tournament_type_id_tournament_types"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tournament_rebuy_configs")),
    )
    op.create_index(
        op.f("ix_tournament_rebuy_configs_tournament_type_id"),
        "tournament_rebuy_configs",
        ["tournament_type_id"],
    )

    op.create_table(
        "weekly_tournament_templates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("tournament_type_id", sa.Integer(), nullable=False),
        sa.Column("rotation_order", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "weekday >= 0 AND weekday <= 6",
            name=op.f("ck_weekly_tournament_templates_weekday_range"),
        ),
        sa.CheckConstraint(
            "rotation_order IS NULL OR rotation_order > 0",
            name=op.f("ck_weekly_tournament_templates_rotation_order_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["tournament_type_id"],
            ["tournament_types.id"],
            name=op.f("fk_weekly_tournament_templates_tournament_type_id_tournament_types"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_weekly_tournament_templates")),
    )
    op.create_index(
        op.f("ix_weekly_tournament_templates_is_active"),
        "weekly_tournament_templates",
        ["is_active"],
    )
    op.create_index(
        op.f("ix_weekly_tournament_templates_tournament_type_id"),
        "weekly_tournament_templates",
        ["tournament_type_id"],
    )
    op.create_index(
        op.f("ix_weekly_tournament_templates_weekday"),
        "weekly_tournament_templates",
        ["weekday"],
    )

    with op.batch_alter_table("scoring_configs") as batch_op:
        batch_op.drop_constraint("knockout_points_nonnegative", type_="check")
        batch_op.drop_constraint("boss_knockout_points_nonnegative", type_="check")
        batch_op.alter_column("knockout_points", new_column_name="knockout_small_points")
        batch_op.alter_column(
            "boss_knockout_points",
            new_column_name="knockout_big_points",
        )
        batch_op.create_check_constraint(
            "knockout_small_points_nonnegative",
            "knockout_small_points >= 0",
        )
        batch_op.create_check_constraint(
            "knockout_big_points_nonnegative",
            "knockout_big_points >= 0",
        )

    seed_tournament_types()

    with op.batch_alter_table("tournaments") as batch_op:
        batch_op.add_column(sa.Column("tournament_type_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            op.f("fk_tournaments_tournament_type_id_tournament_types"),
            "tournament_types",
            ["tournament_type_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_index(
            op.f("ix_tournaments_tournament_type_id"),
            ["tournament_type_id"],
        )

    op.execute(
        """
        UPDATE tournaments
        SET tournament_type_id = (
            SELECT id FROM tournament_types
            WHERE code = CASE tournaments.type
                WHEN 1 THEN 'bounty'
                WHEN 2 THEN 'classic'
                WHEN 3 THEN 'freezeout'
                ELSE 'bounty'
            END
        )
        """
    )

    with op.batch_alter_table("tournaments") as batch_op:
        batch_op.drop_constraint("type_supported", type_="check")
        batch_op.drop_column("type")
        batch_op.alter_column(
            "tournament_type_id",
            existing_type=sa.Integer(),
            nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("tournaments") as batch_op:
        batch_op.add_column(sa.Column("type", sa.Integer(), nullable=True))

    op.execute(
        """
        UPDATE tournaments
        SET type = (
            SELECT CASE tournament_types.code
                WHEN 'classic' THEN 2
                WHEN 'freezeout' THEN 3
                ELSE 1
            END
            FROM tournament_types
            WHERE tournament_types.id = tournaments.tournament_type_id
        )
        """
    )

    with op.batch_alter_table("tournaments") as batch_op:
        batch_op.drop_index(op.f("ix_tournaments_tournament_type_id"))
        batch_op.drop_constraint(
            op.f("fk_tournaments_tournament_type_id_tournament_types"),
            type_="foreignkey",
        )
        batch_op.drop_column("tournament_type_id")
        batch_op.alter_column("type", existing_type=sa.Integer(), nullable=False)
        batch_op.create_check_constraint("type_supported", "type IN (1, 2, 3)")

    with op.batch_alter_table("scoring_configs") as batch_op:
        batch_op.drop_constraint("knockout_small_points_nonnegative", type_="check")
        batch_op.drop_constraint("knockout_big_points_nonnegative", type_="check")
        batch_op.alter_column("knockout_small_points", new_column_name="knockout_points")
        batch_op.alter_column(
            "knockout_big_points",
            new_column_name="boss_knockout_points",
        )
        batch_op.create_check_constraint(
            "knockout_points_nonnegative",
            "knockout_points >= 0",
        )
        batch_op.create_check_constraint(
            "boss_knockout_points_nonnegative",
            "boss_knockout_points >= 0",
        )

    op.drop_index(
        op.f("ix_weekly_tournament_templates_weekday"),
        table_name="weekly_tournament_templates",
    )
    op.drop_index(
        op.f("ix_weekly_tournament_templates_tournament_type_id"),
        table_name="weekly_tournament_templates",
    )
    op.drop_index(
        op.f("ix_weekly_tournament_templates_is_active"),
        table_name="weekly_tournament_templates",
    )
    op.drop_table("weekly_tournament_templates")
    op.drop_index(
        op.f("ix_tournament_rebuy_configs_tournament_type_id"),
        table_name="tournament_rebuy_configs",
    )
    op.drop_table("tournament_rebuy_configs")
    op.drop_index(
        op.f("ix_tournament_economy_configs_tournament_type_id"),
        table_name="tournament_economy_configs",
    )
    op.drop_table("tournament_economy_configs")
    op.drop_index(
        op.f("ix_tournament_type_rules_tournament_type_id"),
        table_name="tournament_type_rules",
    )
    op.drop_table("tournament_type_rules")
    op.drop_index(op.f("ix_tournament_types_status"), table_name="tournament_types")
    op.drop_table("tournament_types")


def seed_tournament_types() -> None:
    for code, name, description in TOURNAMENT_TYPES:
        op.execute(
            sa.text(
                """
                INSERT INTO tournament_types (
                    code, name, description, status, created_at, updated_at
                )
                VALUES (:code, :name, :description, 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            ).bindparams(code=code, name=name, description=description)
        )

    for code, rule in RULES.items():
        points_multiplier, prize_multiplier, places, knockout_mode = rule
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
                SELECT id, :points_multiplier, :prize_multiplier, :places,
                    :knockout_mode, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                FROM tournament_types
                WHERE code = :code
                """
            ).bindparams(
                code=code,
                points_multiplier=points_multiplier,
                prize_multiplier=prize_multiplier,
                places=places,
                knockout_mode=knockout_mode,
            )
        )

    for code in STANDARD_ECONOMY_CODES:
        insert_economy(code, 600, 20_000, 800, 125_000)
        insert_rebuys(code, STANDARD_REBUYS)

    insert_economy("freezeout", 1000, 50_000, 1000, 175_000)
    insert_rebuys("freezeout", [(1, 1000, 75_000)])

    insert_economy("double_double", 800, 40_000, 800, 200_000)
    insert_rebuys("double_double", DOUBLE_DOUBLE_REBUYS)

    for weekday, code, rotation_order in WEEKLY_TEMPLATES:
        op.execute(
            sa.text(
                """
                INSERT INTO weekly_tournament_templates (
                    weekday,
                    tournament_type_id,
                    rotation_order,
                    is_active,
                    created_at,
                    updated_at
                )
                SELECT :weekday, id, :rotation_order, 1,
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                FROM tournament_types
                WHERE code = :code
                """
            ).bindparams(weekday=weekday, code=code, rotation_order=rotation_order)
        )


def insert_economy(
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
            """
        ).bindparams(
            code=code,
            entry_fee=entry_fee,
            entry_stack=entry_stack,
            addon_fee=addon_fee,
            addon_stack=addon_stack,
        )
    )


def insert_rebuys(code: str, rebuys: list[tuple[int, int, int]]) -> None:
    for rebuy_order, fee, stack in rebuys:
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
                SELECT id, :rebuy_order, :fee, :stack,
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                FROM tournament_types
                WHERE code = :code
                """
            ).bindparams(
                code=code,
                rebuy_order=rebuy_order,
                fee=fee,
                stack=stack,
            )
        )
