from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.clock import Clock, club_clock
from app.config import settings
from app.db.models.enums import UserRole
from app.db.repositories.hall_of_fame_repository import HallOfFameRepository
from app.db.repositories.season_repository import SeasonRepository
from app.db.repositories.tournament_photo_repository import TournamentPhotoRepository
from app.db.repositories.tournament_repository import TournamentRepository
from app.db.repositories.tournament_result_repository import TournamentResultRepository
from app.domain.open_tournament_edit_policy import can_edit_open_tournament_for_actor
from app.domain.tournament_day import resolve_tournament_day
from app.services.access_policy import access_policy
from app.services.media_gateway import MediaContent, MediaGatewayError, TelegramMediaGateway


class MediaNotFoundError(ValueError):
    pass


class MediaUnavailableError(RuntimeError):
    pass


class MediaReadService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        gateway: TelegramMediaGateway,
        *,
        clock: Clock = club_clock,
        tournament_day_start_hour: int = settings.tournament_day_start_hour,
    ) -> None:
        self._session_factory = session_factory
        self._gateway = gateway
        self._clock = clock
        self._tournament_day_start_hour = tournament_day_start_hour

    async def get_tournament_photo(
        self,
        actor_user_id: int,
        photo_id: int,
    ) -> MediaContent:
        async with self._session_factory() as session:
            actor = await access_policy.require_active_user(session, actor_user_id)
            photo = await TournamentPhotoRepository(session).get_by_id(photo_id)
            if photo is None:
                raise MediaNotFoundError
            tournament = await TournamentRepository(session).get_by_id(photo.tournament_id)
            if tournament is None:
                raise MediaNotFoundError
            can_edit = actor.role in {UserRole.ADMIN, UserRole.SUPERADMIN} and (
                can_edit_open_tournament_for_actor(
                    actor_role=actor.role,
                    tournament_status=tournament.status,
                    tournament_date=tournament.date,
                    business_date=resolve_tournament_day(
                        self._clock,
                        self._tournament_day_start_hour,
                    ),
                    admin_current_day_only=False,
                )
            )
            if not can_edit:
                own_result = await TournamentResultRepository(session).get_by_tournament_and_player(
                    tournament.id, actor.id
                )
                if own_result is None:
                    raise MediaNotFoundError
            source_reference = photo.telegram_file_id
        return await self._download(source_reference)

    async def get_hall_of_fame_photo(
        self,
        actor_user_id: int,
        photo_id: int,
    ) -> MediaContent:
        async with self._session_factory() as session:
            await access_policy.require_active_user(session, actor_user_id)
            photo = await HallOfFameRepository(session).get_photo_by_id(photo_id)
            if photo is None:
                raise MediaNotFoundError
            season = await SeasonRepository(session).get_by_id(photo.season_id)
            if season is None or season.starts_at > self._clock.today():
                raise MediaNotFoundError
            source_reference = photo.telegram_file_id
        return await self._download(source_reference)

    async def _download(self, source_reference: str) -> MediaContent:
        try:
            return await self._gateway.download_photo(source_reference)
        except MediaGatewayError as exc:
            raise MediaUnavailableError from exc
