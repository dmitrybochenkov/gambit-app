from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.clock import Clock, club_clock
from app.db.models import Season, User
from app.db.models.enums import HallOfFameAchievementKind
from app.db.repositories.hall_of_fame_repository import (
    HallOfFameAchievementRow,
    HallOfFameRepository,
)
from app.db.repositories.season_repository import SeasonRepository
from app.db.repositories.user_repository import UserRepository
from app.db.session import SessionFactory
from app.domain.hall_of_fame import SINGLETON_ACHIEVEMENT_KINDS
from app.services.access_policy import access_policy
from app.services.dto.achievements import AchievementTypeView
from app.services.dto.hall_of_fame import (
    HallOfFameAchievementManagementView,
    HallOfFameCandidateView,
    HallOfFameEntryView,
    HallOfFamePhotoView,
    HallOfFameSeasonListItemView,
)
from app.services.dto.users import UserView
from app.services.player_search import rank_player_candidates
from app.services.user_common import UserNotFoundError, required_user_view


class HallOfFameSeasonNotFoundError(ValueError):
    pass


class HallOfFameAchievementNotFoundError(ValueError):
    pass


class HallOfFameManagementService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Clock = club_clock,
    ) -> None:
        self.session_factory = session_factory
        self.clock = clock

    async def list_seasons(
        self,
        superadmin_telegram_id: int,
    ) -> list[HallOfFameSeasonListItemView]:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, superadmin_telegram_id)
            seasons = await SeasonRepository(session).list_started(self.clock.today())
            return [
                HallOfFameSeasonListItemView(
                    season_id=season.id,
                    season_name=season.name,
                    starts_at=season.starts_at,
                    ends_at=season.ends_at,
                )
                for season in seasons
            ]

    async def get_season_hall_of_fame(
        self,
        superadmin_telegram_id: int,
        season_id: int,
    ) -> HallOfFameEntryView:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, superadmin_telegram_id)
            season = await self._require_season(session, season_id)
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

    async def add_achievement(
        self,
        superadmin_telegram_id: int,
        season_id: int,
        player_id: int,
        kind: HallOfFameAchievementKind,
        awarded_at: date,
    ) -> HallOfFameEntryView:
        return await self.set_achievement(
            superadmin_telegram_id,
            season_id,
            player_id,
            kind,
            awarded_at,
        )

    async def set_achievement(
        self,
        superadmin_telegram_id: int,
        season_id: int,
        player_id: int,
        kind: HallOfFameAchievementKind,
        awarded_at: date,
    ) -> HallOfFameEntryView:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, superadmin_telegram_id)
            season = await self._require_season(session, season_id)
            await self._require_user(session, player_id)
            repository = HallOfFameRepository(session)
            if kind in SINGLETON_ACHIEVEMENT_KINDS:
                achievement = await repository.get_singleton_achievement(
                    season_id=season.id, kind=kind
                )
                if achievement is None:
                    await repository.add_achievement(
                        season_id=season.id,
                        player_id=player_id,
                        kind=kind,
                        awarded_at=awarded_at,
                    )
                else:
                    achievement.player_id = player_id
                    achievement.awarded_at = awarded_at
            else:
                await repository.add_achievement(
                    season_id=season.id,
                    player_id=player_id,
                    kind=kind,
                    awarded_at=awarded_at,
                )
            await session.commit()
            return await self._entry_view(session, season)

    async def add_photo(
        self,
        superadmin_telegram_id: int,
        season_id: int,
        *,
        telegram_file_id: str,
        telegram_file_unique_id: str,
    ) -> HallOfFameEntryView:
        async with self.session_factory() as session:
            actor = await access_policy.require_superadmin(session, superadmin_telegram_id)
            season = await self._require_season(session, season_id)
            repository = HallOfFameRepository(session)
            await repository.add_photo(
                season_id=season.id,
                telegram_file_id=telegram_file_id,
                telegram_file_unique_id=telegram_file_unique_id,
                uploaded_by_user_id=actor.id,
            )
            await session.commit()
            return await self._entry_view(session, season)

    async def delete_all_photos(
        self, superadmin_telegram_id: int, season_id: int
    ) -> HallOfFameEntryView:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, superadmin_telegram_id)
            season = await self._require_season(session, season_id)
            await HallOfFameRepository(session).delete_all_photos(season.id)
            await session.commit()
            return await self._entry_view(session, season)

    async def delete_achievement(
        self,
        superadmin_telegram_id: int,
        season_id: int,
        achievement_id: int,
    ) -> HallOfFameEntryView:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, superadmin_telegram_id)
            season = await self._require_season(session, season_id)
            repository = HallOfFameRepository(session)
            achievement = await repository.get_achievement(achievement_id)
            if achievement is None or achievement.season_id != season.id:
                raise HallOfFameAchievementNotFoundError
            await repository.delete_achievement(achievement)
            await session.commit()
            return await self._entry_view(session, season)

    async def _require_season(
        self,
        session: AsyncSession,
        season_id: int,
    ) -> Season:
        season = await SeasonRepository(session).get_by_id(season_id)
        if season is None or season.starts_at > self.clock.today():
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
        repository = HallOfFameRepository(session)
        achievement_rows = (await repository.list_achievements_for_seasons((season.id,))).get(
            season.id, ()
        )
        photo_rows = (await repository.list_photos_for_seasons((season.id,))).get(season.id, ())
        achievement_types = await repository.list_achievement_types()
        champion_row = next(
            (
                row
                for row in achievement_rows
                if row.kind == HallOfFameAchievementKind.RATING_WINNER
            ),
            None,
        )
        knockout_row = next(
            (
                row
                for row in achievement_rows
                if row.kind == HallOfFameAchievementKind.KO_RATING_WINNER
            ),
            None,
        )
        return HallOfFameEntryView(
            season_id=season.id,
            season_name=season.name,
            starts_at=season.starts_at,
            ends_at=season.ends_at,
            champion=HallOfFameManagementService._achievement_user(champion_row),
            knockout_leader=HallOfFameManagementService._achievement_user(knockout_row),
            photos=tuple(
                HallOfFamePhotoView(
                    id=row.id,
                    telegram_file_id=row.telegram_file_id,
                    telegram_file_unique_id=row.telegram_file_unique_id,
                    position=row.position,
                )
                for row in photo_rows
            ),
            achievements=tuple(
                HallOfFameAchievementManagementView(
                    id=row.id,
                    player=HallOfFameManagementService._achievement_user(row),
                    kind=row.kind,
                    awarded_at=row.awarded_at,
                    title=row.title,
                    emoji=row.emoji,
                    custom_emoji_id=row.custom_emoji_id,
                )
                for row in achievement_rows
            ),
            achievement_types=tuple(
                AchievementTypeView(
                    kind=row.kind.value,
                    title=row.title,
                    emoji=row.emoji,
                    custom_emoji_id=row.custom_emoji_id,
                )
                for row in achievement_types
            ),
        )

    @staticmethod
    def _achievement_user(row: HallOfFameAchievementRow | None) -> UserView | None:
        if row is None:
            return None
        return UserView(
            id=row.player_id,
            telegram_id=row.telegram_id,
            display_name=row.display_name,
            status=row.status,
            role=row.role,
            gender=row.gender,
        )


hall_of_fame_management_service = HallOfFameManagementService(SessionFactory)
