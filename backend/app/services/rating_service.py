from datetime import date
from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.clock import Clock, club_clock
from app.db.models import Season
from app.db.repositories.rating_repository import (
    KnockoutsRatingRow,
    PointsRatingRow,
    RatingHonours,
    RatingRepository,
)
from app.db.repositories.season_repository import SeasonRepository
from app.db.session import SessionFactory
from app.services.access_policy import ActiveUserRequiredError, access_policy
from app.services.dto.seasons import SeasonOptionView
from app.services.dto.statistics.rating import (
    KnockoutsRatingView,
    PointsRatingView,
    RatingResultView,
)
from app.services.dto.statistics.titles import PlayerTitleKind, PlayerTitleOccurrenceView
from app.services.season_options import list_started_season_options


class RatingKind(StrEnum):
    CURRENT_SEASON = "current_season"
    ALL_TIME = "all_time"
    KNOCKOUTS_CURRENT_SEASON = "knockouts_current_season"
    KNOCKOUTS_ALL_TIME = "knockouts_all_time"
    SELECTED_SEASON = "selected_season"
    KNOCKOUTS_SELECTED_SEASON = "knockouts_selected_season"


class RatingNotAllowedError(ValueError):
    pass


class RatingSeasonNotFoundError(ValueError):
    pass


class RatingFutureSeasonError(ValueError):
    pass


class RatingService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Clock = club_clock,
    ) -> None:
        self.session_factory = session_factory
        self.clock = clock

    async def get_rating_for_player(
        self,
        telegram_id: int,
        kind: RatingKind,
        season_id: int | None = None,
        today: date | None = None,
    ) -> RatingResultView:
        business_date = today or self.clock.today()
        async with self.session_factory() as session:
            try:
                player = await access_policy.require_active_user(session, telegram_id)
            except ActiveUserRequiredError as exc:
                raise RatingNotAllowedError from exc
            title, rows = await self._get_rating(
                rating_repository=RatingRepository(session),
                season_repository=SeasonRepository(session),
                kind=kind,
                season_id=season_id,
                today=business_date,
            )
            return RatingResultView(
                title=title,
                rows=rows,
                current_player_id=player.id,
            )

    async def list_rating_seasons(
        self,
        telegram_id: int,
        today: date | None = None,
    ) -> list[SeasonOptionView]:
        business_date = today or self.clock.today()
        async with self.session_factory() as session:
            try:
                await access_policy.require_active_user(session, telegram_id)
            except ActiveUserRequiredError as exc:
                raise RatingNotAllowedError from exc
            return await list_started_season_options(SeasonRepository(session), business_date)

    @staticmethod
    async def _get_rating(
        rating_repository: RatingRepository,
        season_repository: SeasonRepository,
        kind: RatingKind,
        season_id: int | None,
        today: date,
    ) -> tuple[str, list[PointsRatingView] | list[KnockoutsRatingView]]:
        honours = await rating_repository.get_rating_honours(today)
        if kind == RatingKind.CURRENT_SEASON:
            season = await season_repository.get_for_date(today)
            if season is None:
                return "Рейтинг — текущий сезон", []
            return (
                "Рейтинг — текущий сезон",
                [
                    points_rating_view(row, honours)
                    for row in await rating_repository.get_points_rating(
                        season_id=season.id if season else None,
                    )
                ],
            )
        if kind == RatingKind.ALL_TIME:
            return (
                "Рейтинг — за всё время",
                [
                    points_rating_view(row, honours)
                    for row in await rating_repository.get_points_rating()
                ],
            )
        if kind == RatingKind.KNOCKOUTS_CURRENT_SEASON:
            season = await season_repository.get_for_date(today)
            if season is None:
                return "Рейтинг по нокаутам — текущий сезон", []
            return (
                "Рейтинг по нокаутам — текущий сезон",
                [
                    knockouts_rating_view(row, honours)
                    for row in await rating_repository.get_knockouts_rating(
                        season_id=season.id if season else None,
                    )
                ],
            )
        if kind == RatingKind.SELECTED_SEASON:
            season = await _require_started_season(season_repository, season_id, today)
            return (
                f"Рейтинг — {season.name}",
                [
                    points_rating_view(row, honours)
                    for row in await rating_repository.get_points_rating(season_id=season.id)
                ],
            )
        if kind == RatingKind.KNOCKOUTS_SELECTED_SEASON:
            season = await _require_started_season(season_repository, season_id, today)
            return (
                f"Рейтинг по нокаутам — {season.name}",
                [
                    knockouts_rating_view(row, honours)
                    for row in await rating_repository.get_knockouts_rating(
                        season_id=season.id,
                    )
                ],
            )
        return (
            "Рейтинг по нокаутам — за всё время",
            [
                knockouts_rating_view(row, honours)
                for row in await rating_repository.get_knockouts_rating()
            ],
        )


async def _require_started_season(
    season_repository: SeasonRepository,
    season_id: int | None,
    today: date,
) -> Season:
    if season_id is None:
        raise RatingSeasonNotFoundError
    season = await season_repository.get_by_id(season_id)
    if season is None:
        raise RatingSeasonNotFoundError
    if season.starts_at > today:
        raise RatingFutureSeasonError
    return season


def points_rating_view(row: PointsRatingRow, honours: RatingHonours) -> PointsRatingView:
    player_id = int(row.player_id)
    return PointsRatingView(
        player_id=row.player_id,
        display_name=row.display_name,
        total_points=row.total_points,
        tournaments_count=row.tournaments_count,
        title_badges=_title_occurrences(honours, player_id),
        season_champion_titles_count=honours.season_champion_titles_by_player_id.get(
            player_id,
            0,
        ),
    )


def knockouts_rating_view(row: KnockoutsRatingRow, honours: RatingHonours) -> KnockoutsRatingView:
    player_id = int(row.player_id)
    return KnockoutsRatingView(
        player_id=row.player_id,
        display_name=row.display_name,
        knockouts_count=row.knockouts_count,
        big_knockouts_count=row.big_knockouts_count,
        knockout_tournaments_count=row.knockout_tournaments_count,
        title_badges=_title_occurrences(honours, player_id),
        season_champion_titles_count=honours.season_champion_titles_by_player_id.get(
            player_id,
            0,
        ),
        season_knockout_leader_titles_count=(
            honours.season_knockout_leader_titles_by_player_id.get(player_id, 0)
        ),
    )


def _title_occurrences(
    honours: RatingHonours,
    player_id: int,
) -> tuple[PlayerTitleOccurrenceView, ...]:
    return tuple(
        PlayerTitleOccurrenceView(
            season_id=row.season_id,
            season_name=row.season_name,
            season_starts_at=row.starts_at,
            kind=PlayerTitleKind(row.kind),
        )
        for row in honours.title_occurrences_by_player_id.get(player_id, ())
    )


rating_service = RatingService(SessionFactory)
