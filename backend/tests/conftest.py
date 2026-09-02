from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.db.factories import create_user
from app.db.models import (
    TournamentEconomyConfig,
    TournamentRebuyConfig,
    TournamentType,
    TournamentTypeRule,
    User,
    WeeklyTournamentTemplate,
)
from app.db.models.enums import KnockoutMode, TournamentTypeStatus

TOURNAMENT_TYPE_IDS = {
    "bounty": 1,
    "classic": 2,
    "freezeout": 3,
    "double_double": 4,
    "mystery_bounty": 5,
    "boss_bounty": 6,
    "bounty_v2": 8,
    "classic_v2": 9,
    "freezeout_v2": 10,
    "deep_stack": 11,
    "white_party": 12,
}

TOURNAMENT_TYPE_NAMES = {
    "bounty": "Баунти турнир",
    "classic": "Классика",
    "freezeout": "Фризаут",
    "double_double": "Double Double",
    "mystery_bounty": "Mystery Bounty",
    "boss_bounty": "Boss Bounty",
    "bounty_v2": "Bounty",
    "classic_v2": "Classic",
    "freezeout_v2": "Freezeout",
    "deep_stack": "Deep Stack",
    "white_party": "White Party Tournament",
}

TOURNAMENT_TYPE_SHORT_NAMES = {
    "bounty": "Bounty",
    "classic": "Classic",
    "freezeout": "Freezeout",
    "double_double": "Double",
    "mystery_bounty": "Mystery",
    "boss_bounty": "Boss",
    "bounty_v2": "Bounty",
    "classic_v2": "Classic",
    "freezeout_v2": "Freezeout",
    "deep_stack": "Deep Stack",
    "white_party": "White Party",
}
TOURNAMENT_TYPE_DESCRIPTIONS = {
    "bounty": (
        "Динамические нокауты: до финального стола малые КО, на финальном столе большие КО."
    ),
    "classic": (
        "Классический турнир. Комбо-бонусы выплачиваются фишками "
        "во время игры и не влияют на рейтинг."
    ),
    "freezeout": "Формат для скилловых игроков. Рейтинг за 1 и 2 место умножается на 1.5.",
    "double_double": "Удвоенный рейтинг и увеличенные стеки.",
    "mystery_bounty": "Воскресный bounty-формат с mystery-наградами.",
    "boss_bounty": "Воскресный bounty-формат: обычные КО малые, КО босса большие.",
    "bounty_v2": (
        "Динамические нокауты: до финального стола малые КО, на финальном столе большие КО."
    ),
    "classic_v2": (
        "Классический турнир. Комбо-бонусы выплачиваются фишками "
        "во время игры и не влияют на рейтинг."
    ),
    "freezeout_v2": (
        "Формат для скилловых игроков. Рейтинг за 1 и 2 место умножается на 1.5.\n"
        "На этот турнир не действуют привилегии клуба."
    ),
    "deep_stack": "Гарантированный фонд турнира — 2500 очков.",
    "white_party": (
        "Приди в белом — получи фишки к стеку.\nПриди в тёмных очках — получи фишки к стеку."
    ),
}
CREATABLE_TOURNAMENT_TYPE_CODES = {
    "bounty_v2",
    "classic_v2",
    "freezeout_v2",
    "deep_stack",
    "white_party",
    "mystery_bounty",
    "boss_bounty",
}
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
WHITE_PARTY_REBUYS = [
    (1, 800, 40_000),
    (2, 800, 50_000),
    (3, 1000, 80_000),
    (4, 1000, 100_000),
]
TOURNAMENT_TYPE_RULES = {
    "bounty": ("1.00", "1.00", None, KnockoutMode.SMALL_BIG, False),
    "classic": ("1.00", "1.00", None, KnockoutMode.NONE, False),
    "freezeout": ("1.00", "1.50", "[1,2]", KnockoutMode.NONE, False),
    "double_double": ("2.00", "1.00", None, KnockoutMode.NONE, False),
    "mystery_bounty": ("1.00", "1.00", None, KnockoutMode.SMALL, True),
    "boss_bounty": ("1.00", "1.00", None, KnockoutMode.SMALL_BIG, False),
    "bounty_v2": ("1.00", "1.00", None, KnockoutMode.SMALL_BIG, False),
    "classic_v2": ("1.00", "1.00", None, KnockoutMode.NONE, False),
    "freezeout_v2": ("1.00", "1.50", "[1,2]", KnockoutMode.NONE, False),
    "deep_stack": ("1.00", "1.00", None, KnockoutMode.NONE, False),
    "white_party": ("1.00", "1.00", None, KnockoutMode.NONE, False),
}


def tournament_type_id(code: str) -> int:
    return TOURNAMENT_TYPE_IDS[code]


def build_player(
    *,
    telegram_id: int,
    display_name: str,
    **kwargs: object,
) -> User:
    return create_user(
        telegram_id=telegram_id,
        display_name=display_name,
        **kwargs,
    )


def build_tournament_types() -> list[TournamentType]:
    return [
        TournamentType(
            id=tournament_type_id(code),
            code=code,
            name=name,
            short_name=TOURNAMENT_TYPE_SHORT_NAMES[code],
            description=TOURNAMENT_TYPE_DESCRIPTIONS[code],
            status=TournamentTypeStatus.ACTIVE,
            is_creatable=code in CREATABLE_TOURNAMENT_TYPE_CODES,
        )
        for code, name in TOURNAMENT_TYPE_NAMES.items()
    ]


def build_weekly_templates() -> list[WeeklyTournamentTemplate]:
    return [
        WeeklyTournamentTemplate(
            weekday=2,
            tournament_type_id=tournament_type_id("bounty_v2"),
        ),
        WeeklyTournamentTemplate(
            weekday=3,
            tournament_type_id=tournament_type_id("classic_v2"),
        ),
        WeeklyTournamentTemplate(
            weekday=4,
            tournament_type_id=tournament_type_id("freezeout_v2"),
        ),
        WeeklyTournamentTemplate(
            weekday=5,
            tournament_type_id=tournament_type_id("deep_stack"),
        ),
        WeeklyTournamentTemplate(
            weekday=6,
            tournament_type_id=tournament_type_id("mystery_bounty"),
            rotation_order=1,
        ),
        WeeklyTournamentTemplate(
            weekday=6,
            tournament_type_id=tournament_type_id("boss_bounty"),
            rotation_order=2,
        ),
    ]


def build_tournament_economy_configs() -> list[TournamentEconomyConfig]:
    standard_codes = {
        "bounty",
        "classic",
        "bounty_v2",
        "classic_v2",
        "mystery_bounty",
        "boss_bounty",
    }
    configs = [
        TournamentEconomyConfig(
            tournament_type_id=tournament_type_id(code),
            entry_fee=600,
            entry_stack=20_000,
            addon_fee=800,
            addon_stack=125_000,
        )
        for code in standard_codes
    ]
    configs.extend(
        [
            TournamentEconomyConfig(
                tournament_type_id=tournament_type_id("freezeout"),
                entry_fee=1000,
                entry_stack=50_000,
                addon_fee=1000,
                addon_stack=175_000,
            ),
            TournamentEconomyConfig(
                tournament_type_id=tournament_type_id("double_double"),
                entry_fee=800,
                entry_stack=40_000,
                addon_fee=800,
                addon_stack=200_000,
            ),
            TournamentEconomyConfig(
                tournament_type_id=tournament_type_id("deep_stack"),
                entry_fee=800,
                entry_stack=40_000,
                addon_fee=800,
                addon_stack=200_000,
            ),
            TournamentEconomyConfig(
                tournament_type_id=tournament_type_id("freezeout_v2"),
                entry_fee=1000,
                entry_stack=50_000,
                addon_fee=1000,
                addon_stack=175_000,
            ),
            TournamentEconomyConfig(
                tournament_type_id=tournament_type_id("white_party"),
                entry_fee=800,
                entry_stack=30_000,
                addon_fee=1000,
                addon_stack=150_000,
            ),
        ]
    )
    return configs


def build_tournament_rebuy_configs() -> list[TournamentRebuyConfig]:
    configs: list[TournamentRebuyConfig] = []
    for code in {"bounty", "classic", "mystery_bounty", "boss_bounty"}:
        configs.extend(
            TournamentRebuyConfig(
                tournament_type_id=tournament_type_id(code),
                rebuy_order=rebuy_order,
                fee=fee,
                stack=stack,
            )
            for rebuy_order, fee, stack in STANDARD_REBUYS
        )
    for code in {"bounty_v2", "classic_v2"}:
        configs.extend(
            TournamentRebuyConfig(
                tournament_type_id=tournament_type_id(code),
                rebuy_order=rebuy_order,
                fee=800 if rebuy_order == 1 else fee,
                stack=stack,
            )
            for rebuy_order, fee, stack in STANDARD_REBUYS
        )
    configs.append(
        TournamentRebuyConfig(
            tournament_type_id=tournament_type_id("freezeout"),
            rebuy_order=1,
            fee=1000,
            stack=75_000,
        )
    )
    configs.append(
        TournamentRebuyConfig(
            tournament_type_id=tournament_type_id("freezeout_v2"),
            rebuy_order=1,
            fee=1000,
            stack=75_000,
        )
    )
    configs.extend(
        TournamentRebuyConfig(
            tournament_type_id=tournament_type_id("double_double"),
            rebuy_order=rebuy_order,
            fee=fee,
            stack=stack,
        )
        for rebuy_order, fee, stack in DOUBLE_DOUBLE_REBUYS
    )
    configs.extend(
        TournamentRebuyConfig(
            tournament_type_id=tournament_type_id("deep_stack"),
            rebuy_order=rebuy_order,
            fee=fee,
            stack=stack,
        )
        for rebuy_order, fee, stack in DOUBLE_DOUBLE_REBUYS
    )
    configs.extend(
        TournamentRebuyConfig(
            tournament_type_id=tournament_type_id("white_party"),
            rebuy_order=rebuy_order,
            fee=fee,
            stack=stack,
        )
        for rebuy_order, fee, stack in WHITE_PARTY_REBUYS
    )
    return configs


def build_tournament_type_rules() -> list[TournamentTypeRule]:
    return [
        TournamentTypeRule(
            tournament_type_id=tournament_type_id(code),
            points_multiplier=points_multiplier,
            prize_place_multiplier=prize_multiplier,
            prize_place_multiplier_places=places,
            knockout_mode=knockout_mode,
            supports_bonus_points=supports_bonus_points,
        )
        for (
            code,
            (
                points_multiplier,
                prize_multiplier,
                places,
                knockout_mode,
                supports_bonus_points,
            ),
        ) in TOURNAMENT_TYPE_RULES.items()
    ]


def seed_tournament_types(session: Session) -> None:
    session.add_all(build_tournament_types())
    session.flush()


async def seed_tournament_types_async(session: AsyncSession) -> None:
    session.add_all(build_tournament_types())
    await session.flush()


async def seed_tournament_configs_async(session: AsyncSession) -> None:
    session.add_all(build_tournament_economy_configs())
    session.add_all(build_tournament_rebuy_configs())
    await session.flush()


async def seed_tournament_rules_async(session: AsyncSession) -> None:
    session.add_all(build_tournament_type_rules())
    await session.flush()


async def seed_weekly_templates_async(session: AsyncSession) -> None:
    session.add_all(build_weekly_templates())
    await session.flush()
