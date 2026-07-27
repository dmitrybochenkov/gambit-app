from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.db.factories import create_player
from app.db.models import (
    Player,
    TournamentEconomyConfig,
    TournamentRebuyConfig,
    TournamentType,
    WeeklyTournamentTemplate,
)
from app.db.models.enums import TournamentTypeStatus

TOURNAMENT_TYPE_IDS = {
    "bounty": 1,
    "classic": 2,
    "freezeout": 3,
    "double_double": 4,
    "mystery_bounty": 5,
    "boss_bounty": 6,
}

TOURNAMENT_TYPE_NAMES = {
    "bounty": "Баунти турнир",
    "classic": "Классика",
    "freezeout": "Фризаут",
    "double_double": "Double Double",
    "mystery_bounty": "Mystery Bounty",
    "boss_bounty": "Boss Bounty",
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


def tournament_type_id(code: str) -> int:
    return TOURNAMENT_TYPE_IDS[code]


def build_player(
    *,
    telegram_id: int,
    display_name: str,
    **kwargs: object,
) -> Player:
    return create_player(
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
            status=TournamentTypeStatus.ACTIVE,
        )
        for code, name in TOURNAMENT_TYPE_NAMES.items()
    ]


def build_weekly_templates() -> list[WeeklyTournamentTemplate]:
    return [
        WeeklyTournamentTemplate(
            weekday=2,
            tournament_type_id=tournament_type_id("bounty"),
        ),
        WeeklyTournamentTemplate(
            weekday=3,
            tournament_type_id=tournament_type_id("classic"),
        ),
        WeeklyTournamentTemplate(
            weekday=4,
            tournament_type_id=tournament_type_id("freezeout"),
        ),
        WeeklyTournamentTemplate(
            weekday=5,
            tournament_type_id=tournament_type_id("double_double"),
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
    standard_codes = {"bounty", "classic", "mystery_bounty", "boss_bounty"}
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
    configs.append(
        TournamentRebuyConfig(
            tournament_type_id=tournament_type_id("freezeout"),
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
    return configs


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


async def seed_weekly_templates_async(session: AsyncSession) -> None:
    session.add_all(build_weekly_templates())
    await session.flush()
