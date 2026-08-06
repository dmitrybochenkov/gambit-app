from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    Tournament,
    TournamentResult,
    TournamentType,
    User,
    WeeklyTournamentTemplate,
)
from app.db.models.enums import TournamentStatus, TournamentTypeStatus
from app.db.repositories.result_scopes import closed_tournament_filter


@dataclass(frozen=True)
class HistoricalTournamentRow:
    id: int
    date: date
    tournament_name: str


@dataclass(frozen=True)
class HistoricalTournamentResultRow:
    tournament_id: int
    tournament_date: date
    tournament_name: str
    player_id: int
    display_name: str
    place: int | None
    knockouts_count: int
    big_knockouts_count: int
    total_points: Decimal


class TournamentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_upcoming_active(
        self,
        from_date: date,
        limit: int = 20,
    ) -> list[Tournament]:
        result = await self.session.execute(
            select(Tournament)
            .options(selectinload(Tournament.tournament_type))
            .where(
                Tournament.status == TournamentStatus.ACTIVE,
                Tournament.date >= from_date,
            )
            .order_by(Tournament.date, Tournament.tournament_type_id)
            .limit(limit)
        )
        return list(result.scalars())

    async def get_by_id(self, tournament_id: int) -> Tournament | None:
        result = await self.session.execute(
            select(Tournament)
            .options(selectinload(Tournament.tournament_type))
            .where(Tournament.id == tournament_id)
        )
        return result.scalar_one_or_none()

    async def exists_for_date_and_type_id(
        self,
        tournament_date: date,
        tournament_type_id: int,
    ) -> bool:
        result = await self.session.execute(
            select(Tournament.id).where(
                Tournament.date == tournament_date,
                Tournament.tournament_type_id == tournament_type_id,
            )
        )
        return result.scalar_one_or_none() is not None

    async def exists_for_date(self, tournament_date: date) -> bool:
        result = await self.session.execute(
            select(Tournament.id).where(Tournament.date == tournament_date)
        )
        return result.scalar_one_or_none() is not None

    async def get_latest_sunday_rotation_tournament_before(
        self,
        target_date: date,
        allowed_type_codes: tuple[str, ...],
    ) -> Tournament | None:
        result = await self.session.execute(
            select(Tournament)
            .join(Tournament.tournament_type)
            .options(selectinload(Tournament.tournament_type))
            .where(
                Tournament.date < target_date,
                Tournament.status != TournamentStatus.CANCELLED,
                TournamentType.code.in_(allowed_type_codes),
                func.strftime("%w", Tournament.date) == "0",
            )
            .order_by(Tournament.date.desc(), Tournament.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_active_tournament_type_by_code(self, code: str) -> TournamentType | None:
        result = await self.session.execute(
            select(TournamentType).where(
                TournamentType.code == code,
                TournamentType.status == TournamentTypeStatus.ACTIVE,
            )
        )
        return result.scalar_one_or_none()

    async def list_active_weekly_templates(self) -> list[WeeklyTournamentTemplate]:
        result = await self.session.execute(
            select(WeeklyTournamentTemplate)
            .where(WeeklyTournamentTemplate.is_active.is_(True))
            .join(WeeklyTournamentTemplate.tournament_type)
            .where(
                WeeklyTournamentTemplate.tournament_type.has(
                    and_(
                        TournamentType.status == TournamentTypeStatus.ACTIVE,
                        TournamentType.code != "legacy_unknown",
                    )
                )
            )
            .options(selectinload(WeeklyTournamentTemplate.tournament_type))
            .order_by(
                WeeklyTournamentTemplate.weekday,
                WeeklyTournamentTemplate.rotation_order,
                WeeklyTournamentTemplate.id,
            )
        )
        return list(result.scalars())

    async def list_result_years(self) -> list[int]:
        result = await self.session.execute(
            select(func.strftime("%Y", Tournament.date).label("year"))
            .join(TournamentResult, TournamentResult.tournament_id == Tournament.id)
            .where(closed_tournament_filter())
            .group_by("year")
            .order_by(func.strftime("%Y", Tournament.date).desc())
        )
        return [int(year) for year in result.scalars()]

    async def list_result_months(self, year: int) -> list[int]:
        result = await self.session.execute(
            select(func.strftime("%m", Tournament.date).label("month"))
            .join(TournamentResult, TournamentResult.tournament_id == Tournament.id)
            .where(
                closed_tournament_filter(),
                func.strftime("%Y", Tournament.date) == str(year),
            )
            .group_by("month")
            .order_by(func.strftime("%m", Tournament.date).desc())
        )
        return [int(month) for month in result.scalars()]

    async def list_result_tournaments(
        self,
        year: int,
        month: int,
    ) -> list[HistoricalTournamentRow]:
        result = await self.session.execute(
            select(
                Tournament.id,
                Tournament.date,
                TournamentType.name.label("tournament_name"),
            )
            .join(TournamentType, TournamentType.id == Tournament.tournament_type_id)
            .join(TournamentResult, TournamentResult.tournament_id == Tournament.id)
            .where(
                closed_tournament_filter(),
                func.strftime("%Y", Tournament.date) == str(year),
                func.strftime("%m", Tournament.date) == f"{month:02d}",
            )
            .group_by(Tournament.id, Tournament.date, TournamentType.name)
            .order_by(Tournament.date.desc(), Tournament.id.desc())
        )
        return [
            HistoricalTournamentRow(
                id=row.id,
                date=row.date,
                tournament_name=row.tournament_name,
            )
            for row in result
        ]

    async def get_tournament_result(
        self,
        tournament_id: int,
    ) -> list[HistoricalTournamentResultRow]:
        total_knockouts = TournamentResult.knockouts_count + TournamentResult.big_knockouts_count
        total_points = (
            TournamentResult.tournament_points
            + TournamentResult.knockout_points
            + TournamentResult.bonus_points
        )
        result = await self.session.execute(
            select(
                Tournament.id.label("tournament_id"),
                Tournament.date.label("tournament_date"),
                TournamentType.name.label("tournament_name"),
                User.id.label("player_id"),
                User.display_name,
                TournamentResult.place,
                TournamentResult.knockouts_count,
                TournamentResult.big_knockouts_count,
                total_points.label("total_points"),
            )
            .join(TournamentType, TournamentType.id == Tournament.tournament_type_id)
            .join(TournamentResult, TournamentResult.tournament_id == Tournament.id)
            .join(User, User.id == TournamentResult.player_id)
            .where(
                Tournament.id == tournament_id,
                closed_tournament_filter(),
            )
            .order_by(
                TournamentResult.place.is_(None),
                TournamentResult.place,
                total_knockouts.desc(),
                TournamentResult.big_knockouts_count.desc(),
                TournamentResult.player_id,
            )
        )
        return [
            HistoricalTournamentResultRow(
                tournament_id=row.tournament_id,
                tournament_date=row.tournament_date,
                tournament_name=row.tournament_name,
                player_id=row.player_id,
                display_name=row.display_name,
                place=row.place,
                knockouts_count=row.knockouts_count,
                big_knockouts_count=row.big_knockouts_count,
                total_points=row.total_points,
            )
            for row in result
        ]
