from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.clock import Clock, club_clock
from app.db.models import User
from app.db.repositories.hall_of_fame_repository import HallOfFameRepository
from app.db.repositories.tournament_repository import (
    HistoricalTournamentResultRow,
    TournamentRepository,
)
from app.db.session import SessionFactory
from app.services.access_policy import ActiveUserRequiredError, access_policy
from app.services.dto.statistics.hall_of_fame import HallOfFameSeasonView
from app.services.dto.statistics.history import (
    HistoricalTournamentResultRowView,
    HistoricalTournamentResultView,
    HistoricalTournamentView,
    HistoryMonthView,
    HistoryYearView,
    PlayerHistoryTournamentView,
)

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
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Clock = club_clock,
    ) -> None:
        self.session_factory = session_factory
        self.clock = clock

    async def list_history_years(self, telegram_id: int) -> list[HistoryYearView]:
        async with self.session_factory() as session:
            await self._ensure_user_can_view_statistics(
                session, telegram_id, HistoryNotAllowedError
            )
            years = await TournamentRepository(session).list_result_years()
            return [HistoryYearView(year=year) for year in years]

    async def list_history_months(
        self,
        telegram_id: int,
        year: int,
    ) -> list[HistoryMonthView]:
        async with self.session_factory() as session:
            await self._ensure_user_can_view_statistics(
                session, telegram_id, HistoryNotAllowedError
            )
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
            await self._ensure_user_can_view_statistics(
                session, telegram_id, HistoryNotAllowedError
            )
            rows = await TournamentRepository(session).list_result_tournaments(year, month)
            return [
                HistoricalTournamentView(
                    id=row.id,
                    date=row.date,
                    display_name=historical_tournament_display_name(
                        tournament_name=row.tournament_name,
                        tournament_short_name=row.tournament_short_name,
                        tournament_type_code=row.tournament_type_code,
                        has_knockouts=row.has_knockouts,
                    ),
                )
                for row in rows
            ]

    async def get_historical_tournament_result(
        self,
        telegram_id: int,
        tournament_id: int,
    ) -> HistoricalTournamentResultView:
        async with self.session_factory() as session:
            await self._ensure_user_can_view_statistics(
                session, telegram_id, HistoryNotAllowedError
            )
            rows = await TournamentRepository(session).get_tournament_result(tournament_id)
            if not rows:
                raise HistoricalTournamentNotFoundError
            return historical_tournament_result_view(rows)

    async def list_player_history(self, telegram_id: int) -> list[PlayerHistoryTournamentView]:
        async with self.session_factory() as session:
            player = await self._ensure_user_can_view_statistics(
                session, telegram_id, HistoryNotAllowedError
            )
            rows = await TournamentRepository(session).list_player_result_tournaments(player.id)
            return [player_history_tournament_view(row) for row in rows]

    async def get_player_history_tournament_result(
        self,
        telegram_id: int,
        tournament_id: int,
    ) -> HistoricalTournamentResultView:
        async with self.session_factory() as session:
            player = await self._ensure_user_can_view_statistics(
                session, telegram_id, HistoryNotAllowedError
            )
            rows = await TournamentRepository(session).get_tournament_result(tournament_id)
            if not rows or all(row.player_id != player.id for row in rows):
                raise HistoricalTournamentNotFoundError
            return historical_tournament_result_view(rows)

    async def get_hall_of_fame(self, telegram_id: int) -> list[HallOfFameSeasonView]:
        async with self.session_factory() as session:
            await self._ensure_user_can_view_statistics(
                session, telegram_id, HallOfFameNotAllowedError
            )
            rows = await HallOfFameRepository(session).list_completed_entries(self.clock.today())
            return [
                HallOfFameSeasonView(
                    season_id=row.season_id,
                    season_name=row.season_name,
                    starts_at=row.starts_at,
                    ends_at=row.ends_at,
                    champion_player_id=row.champion_player_id,
                    champion_display_name=row.champion_display_name,
                    knockout_leader_player_id=row.knockout_leader_player_id,
                    knockout_leader_display_name=row.knockout_leader_display_name,
                    champion_photo_file_id=row.champion_photo_file_id,
                    knockout_photo_file_id=row.knockout_photo_file_id,
                )
                for row in rows
            ]

    @staticmethod
    async def _ensure_user_can_view_statistics(
        session: AsyncSession,
        telegram_id: int,
        error_class: type[ValueError],
    ) -> User:
        try:
            return await access_policy.require_active_user(session, telegram_id)
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
            display_name=historical_tournament_display_name(
                tournament_name=first_row.tournament_name,
                tournament_short_name=first_row.tournament_name,
                tournament_type_code=first_row.tournament_type_code,
                has_knockouts=first_row.tournament_has_knockouts,
            ),
            tournament_type_code=first_row.tournament_type_code,
            tournament_type_name=first_row.tournament_name,
        ),
        rows=[
            HistoricalTournamentResultRowView(
                player_id=row.player_id,
                display_name=row.display_name,
                place=row.place,
                knockouts_count=row.knockouts_count,
                big_knockouts_count=row.big_knockouts_count,
                tournament_points=row.tournament_points,
                knockout_points=row.knockout_points,
                bonus_points=row.bonus_points,
                total_points=row.total_points,
            )
            for row in rows
        ],
    )


def player_history_tournament_view(
    row: HistoricalTournamentResultRow,
) -> PlayerHistoryTournamentView:
    return PlayerHistoryTournamentView(
        tournament_id=row.tournament_id,
        date=row.tournament_date,
        tournament_type_code=row.tournament_type_code,
        tournament_type_name=historical_tournament_display_name(
            tournament_name=row.tournament_name,
            tournament_short_name=row.tournament_short_name,
            tournament_type_code=row.tournament_type_code,
            has_knockouts=row.tournament_has_knockouts,
        ),
        place=row.place,
        tournament_points=row.tournament_points,
        knockout_points=row.knockout_points,
        bonus_points=row.bonus_points,
        total_points=row.total_points,
        knockouts_count=row.knockouts_count,
        big_knockouts_count=row.big_knockouts_count,
    )


def _month_label(month: int) -> str:
    return MONTH_LABELS[month]


def historical_tournament_display_name(
    *,
    tournament_name: str,
    tournament_short_name: str,
    tournament_type_code: str,
    has_knockouts: bool,
) -> str:
    if tournament_type_code != "legacy_unknown":
        return tournament_short_name
    return "Bounty" if has_knockouts else "Турнир"


user_statistics_service = UserStatisticsService(SessionFactory)
