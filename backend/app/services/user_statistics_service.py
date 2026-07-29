from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.repositories.rating_repository import RatingRepository
from app.db.repositories.tournament_repository import (
    HistoricalTournamentResultRow,
    TournamentRepository,
)
from app.db.repositories.user_repository import UserRepository
from app.db.session import SessionFactory
from app.services.dto import (
    HallOfFameSeasonView,
    HistoricalTournamentResultRowView,
    HistoricalTournamentResultView,
    HistoricalTournamentView,
    HistoryMonthView,
    HistoryYearView,
)
from app.services.user_service import ActiveUserRequiredError, require_active_user

MONTH_LABELS = {
    1: "Январь",
    2: "Февраль",
    3: "Март",
    4: "Апрель",
    5: "Май",
    6: "Июнь",
    7: "Июль",
    8: "Август",
    9: "Сентябрь",
    10: "Октябрь",
    11: "Ноябрь",
    12: "Декабрь",
}


class HistoryNotAllowedError(ValueError):
    pass


class HistoricalTournamentNotFoundError(ValueError):
    pass


class HallOfFameNotAllowedError(ValueError):
    pass


class UserStatisticsService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def list_history_years(self, telegram_id: int) -> list[HistoryYearView]:
        async with self.session_factory() as session:
            await self._require_active_user(session, telegram_id, HistoryNotAllowedError)
            years = await TournamentRepository(session).list_result_years()
            return [HistoryYearView(year=year) for year in years]

    async def list_history_months(
        self,
        telegram_id: int,
        year: int,
    ) -> list[HistoryMonthView]:
        async with self.session_factory() as session:
            await self._require_active_user(session, telegram_id, HistoryNotAllowedError)
            months = await TournamentRepository(session).list_result_months(year)
            return [
                HistoryMonthView(
                    year=year,
                    month=month,
                    label=_month_label(month),
                )
                for month in months
            ]

    async def list_history_tournaments(
        self,
        telegram_id: int,
        year: int,
        month: int,
    ) -> list[HistoricalTournamentView]:
        async with self.session_factory() as session:
            await self._require_active_user(session, telegram_id, HistoryNotAllowedError)
            rows = await TournamentRepository(session).list_result_tournaments(year, month)
            return [
                HistoricalTournamentView(
                    id=row.id,
                    date=row.date,
                    tournament_name=row.tournament_name,
                )
                for row in rows
            ]

    async def get_historical_tournament_result(
        self,
        telegram_id: int,
        tournament_id: int,
    ) -> HistoricalTournamentResultView:
        async with self.session_factory() as session:
            await self._require_active_user(session, telegram_id, HistoryNotAllowedError)
            rows = await TournamentRepository(session).get_tournament_result(tournament_id)
            if not rows:
                raise HistoricalTournamentNotFoundError
            return historical_tournament_result_view(rows)

    async def get_hall_of_fame(self, telegram_id: int) -> list[HallOfFameSeasonView]:
        async with self.session_factory() as session:
            await self._require_active_user(session, telegram_id, HallOfFameNotAllowedError)
            rows = await RatingRepository(session).list_hall_of_fame_seasons()
            return [
                HallOfFameSeasonView(
                    season_id=row.season_id,
                    season_name=row.season_name,
                    starts_at=row.starts_at,
                    champion_player_id=row.champion_player_id,
                    champion_display_name=row.champion_display_name,
                    knockout_leader_player_id=row.knockout_leader_player_id,
                    knockout_leader_display_name=row.knockout_leader_display_name,
                )
                for row in rows
            ]

    @staticmethod
    async def _require_active_user(
        session: AsyncSession,
        telegram_id: int,
        error_class: type[ValueError],
    ) -> None:
        try:
            await require_active_user(UserRepository(session), telegram_id)
        except ActiveUserRequiredError as exc:
            raise error_class from exc


def historical_tournament_result_view(
    rows: list[HistoricalTournamentResultRow],
) -> HistoricalTournamentResultView:
    first_row = rows[0]
    return HistoricalTournamentResultView(
        tournament=HistoricalTournamentView(
            id=first_row.tournament_id,
            date=first_row.tournament_date,
            tournament_name=first_row.tournament_name,
        ),
        rows=[
            HistoricalTournamentResultRowView(
                player_id=row.player_id,
                display_name=row.display_name,
                place=row.place,
                knockouts_count=row.knockouts_count,
                big_knockouts_count=row.big_knockouts_count,
                total_points=row.total_points,
            )
            for row in rows
        ],
    )


def _month_label(month: int) -> str:
    return MONTH_LABELS[month]


user_statistics_service = UserStatisticsService(SessionFactory)
