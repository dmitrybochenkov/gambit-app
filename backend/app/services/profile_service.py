from datetime import date
from decimal import Decimal
from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.clock import Clock, club_clock
from app.db.models import Season
from app.db.repositories.hall_of_fame_repository import HallOfFameRepository
from app.db.repositories.profile_repository import (
    PlayerProfileStats,
    ProfileRepository,
)
from app.db.repositories.rating_repository import RatingRepository
from app.db.repositories.season_repository import SeasonRepository
from app.db.session import SessionFactory
from app.services.access_policy import ActiveUserRequiredError, access_policy
from app.services.dto.seasons import SeasonOptionView
from app.services.dto.statistics.profile import PlayerProfileHonourView, PlayerProfileView
from app.services.season_options import list_started_season_options


class ProfileKind(StrEnum):
    CURRENT_SEASON = "current_season"
    ALL_TIME = "all_time"
    SELECTED_SEASON = "selected_season"


class ProfileNotAllowedError(ValueError):
    pass


class ProfileSeasonNotFoundError(ValueError):
    pass


class ProfileFutureSeasonError(ValueError):
    pass


class ProfileService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Clock = club_clock,
    ) -> None:
        self.session_factory = session_factory
        self.clock = clock

    async def get_profile_for_player(
        self,
        telegram_id: int,
        kind: ProfileKind,
        season_id: int | None = None,
        today: date | None = None,
    ) -> tuple[str, PlayerProfileView | None]:
        business_date = today or self.clock.today()
        async with self.session_factory() as session:
            try:
                user = await access_policy.require_active_user(session, telegram_id)
            except ActiveUserRequiredError as exc:
                raise ProfileNotAllowedError from exc
            return await self._get_profile(
                profile_repository=ProfileRepository(session),
                hall_of_fame_repository=HallOfFameRepository(session),
                rating_repository=RatingRepository(session),
                season_repository=SeasonRepository(session),
                player_id=user.id,
                display_name=user.display_name,
                kind=kind,
                season_id=season_id,
                today=business_date,
            )

    async def list_profile_seasons(
        self,
        telegram_id: int,
        today: date | None = None,
    ) -> list[SeasonOptionView]:
        business_date = today or self.clock.today()
        async with self.session_factory() as session:
            try:
                await access_policy.require_active_user(session, telegram_id)
            except ActiveUserRequiredError as exc:
                raise ProfileNotAllowedError from exc
            return await list_started_season_options(SeasonRepository(session), business_date)

    @staticmethod
    async def _get_profile(
        profile_repository: ProfileRepository,
        hall_of_fame_repository: HallOfFameRepository,
        rating_repository: RatingRepository,
        season_repository: SeasonRepository,
        player_id: int,
        display_name: str,
        kind: ProfileKind,
        season_id: int | None,
        today: date,
    ) -> tuple[str, PlayerProfileView | None]:
        if kind == ProfileKind.CURRENT_SEASON:
            season = await season_repository.get_for_date(today)
            if season is None:
                return (
                    "Твой профиль — текущий сезон",
                    empty_profile(display_name),
                )
            stats = await profile_repository.get_player_stats(
                player_id=player_id,
                season_id=season.id,
            )
            rating_position, rating_participants_count = await _points_rating_position(
                rating_repository,
                player_id,
                season_id=season.id,
            )
            honours = await _player_honours(hall_of_fame_repository, player_id)
            return (
                "Твой профиль — текущий сезон",
                player_profile_view(
                    stats, 
                    rating_position=rating_position,
                    rating_participants_count=rating_participants_count,
                    honours=honours,
                ) if stats else None,
            )
        if kind == ProfileKind.SELECTED_SEASON:
            season = await _require_started_season(season_repository, season_id, today)
            stats = await profile_repository.get_player_stats(
                player_id=player_id,
                season_id=season.id,
            )
            rating_position, rating_participants_count = await _points_rating_position(
                rating_repository,
                player_id,
                season_id=season.id,
            )
            honours = await _player_honours(hall_of_fame_repository, player_id)
            return (
                f"Твой профиль — {season.name}",
                player_profile_view(
                    stats, 
                    rating_position=rating_position,
                    rating_participants_count=rating_participants_count,
                    honours=honours,
                ) if stats else None,
            )
        stats = await profile_repository.get_player_stats(player_id=player_id)
        honours = await _player_honours(hall_of_fame_repository, player_id)
        rating_position, rating_participants_count = await _points_rating_position(
            rating_repository,
            player_id,
        )
        return (
            "Твой профиль — за всё время",
            player_profile_view(
                stats, 
                rating_position=rating_position,
                rating_participants_count=rating_participants_count,
                honours=honours
            ) if stats else None,
        )


def prize_percent(stats: PlayerProfileStats) -> int | None:
    if stats.tournaments_count == 0:
        return None

    prize_places_count = (
        stats.first_places_count
        + stats.second_places_count
        + stats.third_places_count
        + stats.fourth_places_count
        + stats.fifth_places_count
    )

    return round(prize_places_count / stats.tournaments_count * 100)


def player_profile_view(
    stats: PlayerProfileStats,
    *,
    rating_position: int | None,
    rating_participants_count: int,
    honours: tuple[PlayerProfileHonourView, ...] = (),
) -> PlayerProfileView:
    return PlayerProfileView(
        display_name=stats.display_name,
        total_points=stats.total_points,
        knockouts_count=stats.knockouts_count,
        big_knockouts_count=stats.big_knockouts_count,
        tournaments_count=stats.tournaments_count,
        first_places_count=stats.first_places_count,
        second_places_count=stats.second_places_count,
        third_places_count=stats.third_places_count,
        fourth_places_count=stats.fourth_places_count,
        fifth_places_count=stats.fifth_places_count,
        rating_position=rating_position,
        rating_participants_count=rating_participants_count,
        prize_percent=prize_percent(stats),
        honours=honours,
    )


def empty_profile(display_name: str) -> PlayerProfileView:
    return PlayerProfileView(
        display_name=display_name,
        total_points=Decimal("0"),
        knockouts_count=0,
        big_knockouts_count=0,
        tournaments_count=0,
        first_places_count=0,
        second_places_count=0,
        third_places_count=0,
        fourth_places_count=0,
        fifth_places_count=0,
        rating_position=None,
        rating_participants_count=0,
        prize_percent=None,
    )


async def _player_honours(
    repository: HallOfFameRepository,
    player_id: int,
) -> tuple[PlayerProfileHonourView, ...]:
    rows = await repository.list_player_honours(player_id)
    return tuple(
        PlayerProfileHonourView(
            season_name=row.season_name,
            season_starts_at=row.starts_at,
            kind=row.kind,
        )
        for row in rows
    )

async def _points_rating_position(
    repository: RatingRepository,
    player_id: int,
    season_id: int | None = None,
) -> tuple[int | None, int]:
    rows = await repository.get_points_rating(season_id=season_id)
    position = next(
        (
            index
            for index, row in enumerate(rows, start=1)
            if row.player_id == player_id
        ),
        None,
    )
    return position, len(rows)

async def _require_started_season(
    season_repository: SeasonRepository,
    season_id: int | None,
    today: date,
) -> Season:
    if season_id is None:
        raise ProfileSeasonNotFoundError
    season = await season_repository.get_by_id(season_id)
    if season is None:
        raise ProfileSeasonNotFoundError
    if season.starts_at > today:
        raise ProfileFutureSeasonError
    return season


profile_service = ProfileService(SessionFactory)
