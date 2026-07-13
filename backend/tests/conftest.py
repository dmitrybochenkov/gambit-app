from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.db.models import TournamentType, WeeklyTournamentTemplate
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


def tournament_type_id(code: str) -> int:
    return TOURNAMENT_TYPE_IDS[code]


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


def seed_tournament_types(session: Session) -> None:
    session.add_all(build_tournament_types())
    session.flush()


async def seed_tournament_types_async(session: AsyncSession) -> None:
    session.add_all(build_tournament_types())
    await session.flush()


async def seed_weekly_templates_async(session: AsyncSession) -> None:
    session.add_all(build_weekly_templates())
    await session.flush()
