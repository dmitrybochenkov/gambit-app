from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.clock import Clock, club_clock
from app.db.models import Season, User
from app.db.repositories.hall_of_fame_repository import HallOfFameRepository
from app.db.repositories.season_repository import SeasonRepository
from app.db.repositories.user_repository import UserRepository
from app.db.session import SessionFactory
from app.services.access_policy import access_policy
from app.services.dto.hall_of_fame import (
    HallOfFameCandidateView,
    HallOfFameEntryView,
    HallOfFameSeasonListItemView,
)
from app.services.player_search import rank_player_candidates
from app.services.user_common import UserNotFoundError, required_user_view


class HallOfFameSeasonNotFoundError(ValueError):
    pass


class HallOfFamePhotoRole(StrEnum):
    CHAMPION = "champion"
    KNOCKOUT = "knockout"


class HallOfFameManagementService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Clock = club_clock,
    ) -> None:
        self.session_factory = session_factory
        self.clock = clock

    async def list_completed_seasons(
        self,
        superadmin_telegram_id: int,
    ) -> list[HallOfFameSeasonListItemView]:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, superadmin_telegram_id)
            seasons = await SeasonRepository(session).list_completed_before(self.clock.today())
            return [
                HallOfFameSeasonListItemView(
                    season_id=season.id,
                    season_name=season.name,
                    starts_at=season.starts_at,
                    ends_at=season.ends_at,
                )
                for season in seasons
                if season.ends_at is not None
            ]

    async def get_season_hall_of_fame(
        self,
        superadmin_telegram_id: int,
        season_id: int,
    ) -> HallOfFameEntryView:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, superadmin_telegram_id)
            season = await self._require_completed_season(session, season_id)
            return await self._entry_view(session, season)

    async def search_players(
        self,
        superadmin_telegram_id: int,
        query: str,
    ) -> list[HallOfFameCandidateView]:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, superadmin_telegram_id)
            candidates = rank_player_candidates(
                await UserRepository(session).list_hall_of_fame_candidates(),
                query,
                limit=6,
            )
            return [
                HallOfFameCandidateView(
                    user=required_user_view(candidate.user),
                    score=candidate.score,
                    reason=candidate.reason,
                )
                for candidate in candidates
                if isinstance(candidate.user, User)
            ]

    async def get_player(
        self,
        superadmin_telegram_id: int,
        player_id: int,
    ) -> HallOfFameCandidateView:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, superadmin_telegram_id)
            user = await self._require_user(session, player_id)
            return HallOfFameCandidateView(
                user=required_user_view(user),
                score=0,
                reason="",
            )

    async def set_champion(
        self,
        superadmin_telegram_id: int,
        season_id: int,
        player_id: int,
    ) -> HallOfFameEntryView:
        async with self.session_factory() as session:
            actor = await access_policy.require_superadmin(session, superadmin_telegram_id)
            season = await self._require_completed_season(session, season_id)
            await self._require_user(session, player_id)
            repository = HallOfFameRepository(session)
            entry = await repository.get_or_create(
                season_id=season.id,
                updated_by_user_id=actor.id,
            )
            entry.champion_player_id = player_id
            entry.updated_by_user_id = actor.id
            await session.commit()
            return await self._entry_view(session, season)

    async def set_knockout_player(
        self,
        superadmin_telegram_id: int,
        season_id: int,
        player_id: int,
    ) -> HallOfFameEntryView:
        async with self.session_factory() as session:
            actor = await access_policy.require_superadmin(session, superadmin_telegram_id)
            season = await self._require_completed_season(session, season_id)
            await self._require_user(session, player_id)
            repository = HallOfFameRepository(session)
            entry = await repository.get_or_create(
                season_id=season.id,
                updated_by_user_id=actor.id,
            )
            entry.knockout_player_id = player_id
            entry.updated_by_user_id = actor.id
            await session.commit()
            return await self._entry_view(session, season)

    async def set_photo(
        self,
        superadmin_telegram_id: int,
        season_id: int,
        *,
        role: HallOfFamePhotoRole,
        telegram_file_id: str,
        telegram_file_unique_id: str,
    ) -> HallOfFameEntryView:
        async with self.session_factory() as session:
            actor = await access_policy.require_superadmin(session, superadmin_telegram_id)
            season = await self._require_completed_season(session, season_id)
            entry = await HallOfFameRepository(session).get_by_season_id(season.id)
            if entry is None:
                raise HallOfFameSeasonNotFoundError
            if role == HallOfFamePhotoRole.CHAMPION:
                if entry.champion_player_id is None:
                    raise HallOfFameSeasonNotFoundError
                entry.champion_photo_file_id = telegram_file_id
                entry.champion_photo_file_unique_id = telegram_file_unique_id
            else:
                if entry.knockout_player_id is None:
                    raise HallOfFameSeasonNotFoundError
                entry.knockout_photo_file_id = telegram_file_id
                entry.knockout_photo_file_unique_id = telegram_file_unique_id
            entry.updated_by_user_id = actor.id
            await session.commit()
            return await self._entry_view(session, season)

    async def _require_completed_season(
        self,
        session: AsyncSession,
        season_id: int,
    ) -> Season:
        season = await SeasonRepository(session).get_by_id(season_id)
        today = self.clock.today()
        if season is None or season.ends_at is None or season.ends_at >= today:
            raise HallOfFameSeasonNotFoundError
        return season

    @staticmethod
    async def _require_user(session: AsyncSession, user_id: int) -> User:
        user = await UserRepository(session).get_by_id(user_id)
        if user is None:
            raise UserNotFoundError
        return user

    @staticmethod
    async def _entry_view(
        session: AsyncSession,
        season: Season,
    ) -> HallOfFameEntryView:
        entry = await HallOfFameRepository(session).get_by_season_id(season.id)
        champion = None
        knockout_leader = None
        if entry is not None and entry.champion_player_id is not None:
            champion = await UserRepository(session).get_by_id(entry.champion_player_id)
        if entry is not None and entry.knockout_player_id is not None:
            knockout_leader = await UserRepository(session).get_by_id(entry.knockout_player_id)
        if season.ends_at is None:
            raise HallOfFameSeasonNotFoundError
        return HallOfFameEntryView(
            season_id=season.id,
            season_name=season.name,
            starts_at=season.starts_at,
            ends_at=season.ends_at,
            champion=required_user_view(champion) if champion is not None else None,
            knockout_leader=(
                required_user_view(knockout_leader) if knockout_leader is not None else None
            ),
            champion_photo_file_id=entry.champion_photo_file_id if entry is not None else None,
            champion_photo_file_unique_id=(
                entry.champion_photo_file_unique_id if entry is not None else None
            ),
            knockout_photo_file_id=entry.knockout_photo_file_id if entry is not None else None,
            knockout_photo_file_unique_id=(
                entry.knockout_photo_file_unique_id if entry is not None else None
            ),
        )


hall_of_fame_management_service = HallOfFameManagementService(SessionFactory)
