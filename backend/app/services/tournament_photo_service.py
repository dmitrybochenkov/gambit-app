from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.clock import Clock, club_clock
from app.config import settings
from app.db.models import Tournament
from app.db.repositories.tournament_photo_repository import TournamentPhotoRepository
from app.db.repositories.tournament_repository import TournamentRepository
from app.db.session import SessionFactory
from app.domain.open_tournament_edit_policy import can_edit_open_tournament_for_actor
from app.domain.tournament_day import resolve_tournament_day
from app.services.access_policy import access_policy
from app.services.dto.results import TournamentPhotoAddView, TournamentPhotoView
from app.services.result_errors import (
    ResultTournamentNotFoundError,
    TournamentResultsEditingUnavailableError,
)

TOURNAMENT_PHOTO_LIMIT = 10


class TournamentPhotoService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Clock = club_clock,
        tournament_day_start_hour: int = settings.tournament_day_start_hour,
    ) -> None:
        self.session_factory = session_factory
        self.clock = clock
        self.tournament_day_start_hour = tournament_day_start_hour

    async def list_for_tournament(
        self,
        admin_telegram_id: int,
        tournament_id: int,
    ) -> list[TournamentPhotoView]:
        async with self.session_factory() as session:
            actor = await access_policy.require_admin(session, admin_telegram_id)
            await self._require_editable_tournament_for_actor(
                session,
                tournament_id,
                actor_role=actor.role,
            )
            return await self.list_for_tournament_in_session(session, tournament_id)

    async def count_for_tournament(
        self,
        admin_telegram_id: int,
        tournament_id: int,
    ) -> int:
        async with self.session_factory() as session:
            actor = await access_policy.require_admin(session, admin_telegram_id)
            await self._require_editable_tournament_for_actor(
                session,
                tournament_id,
                actor_role=actor.role,
            )
            return await self.count_for_tournament_in_session(session, tournament_id)

    async def add_photo(
        self,
        admin_telegram_id: int,
        tournament_id: int,
        *,
        telegram_file_id: str,
        telegram_file_unique_id: str,
    ) -> TournamentPhotoAddView:
        async with self.session_factory() as session:
            admin = await access_policy.require_admin(session, admin_telegram_id)
            tournament = await self._require_editable_tournament_for_actor(
                session,
                tournament_id,
                actor_role=admin.role,
            )
            repository = TournamentPhotoRepository(session)
            photo_count = await repository.count_for_tournament(tournament.id)
            if photo_count >= TOURNAMENT_PHOTO_LIMIT:
                return TournamentPhotoAddView(
                    tournament_id=tournament.id,
                    photo_count=photo_count,
                    created=False,
                    limit_reached=True,
                )
            if await repository.exists_unique_file(
                tournament_id=tournament.id,
                telegram_file_unique_id=telegram_file_unique_id,
            ):
                return TournamentPhotoAddView(
                    tournament_id=tournament.id,
                    photo_count=photo_count,
                    created=False,
                )
            await repository.add(
                tournament_id=tournament.id,
                telegram_file_id=telegram_file_id,
                telegram_file_unique_id=telegram_file_unique_id,
                uploaded_by_user_id=admin.id,
                position=await repository.next_position(tournament.id),
            )
            await session.commit()
            return TournamentPhotoAddView(
                tournament_id=tournament.id,
                photo_count=photo_count + 1,
                created=True,
            )

    async def delete_photos(
        self,
        admin_telegram_id: int,
        tournament_id: int,
    ) -> int:
        async with self.session_factory() as session:
            actor = await access_policy.require_admin(session, admin_telegram_id)
            tournament = await self._require_editable_tournament_for_actor(
                session,
                tournament_id,
                actor_role=actor.role,
            )
            deleted = await self.delete_all_for_tournament_in_session(session, tournament.id)
            await session.commit()
            return deleted

    async def list_for_tournament_in_session(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> list[TournamentPhotoView]:
        photos = await TournamentPhotoRepository(session).list_for_tournament(tournament_id)
        return [
            TournamentPhotoView(
                id=photo.id,
                tournament_id=photo.tournament_id,
                telegram_file_id=photo.telegram_file_id,
                telegram_file_unique_id=photo.telegram_file_unique_id,
                position=photo.position,
            )
            for photo in photos
        ]

    async def count_for_tournament_in_session(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> int:
        return await TournamentPhotoRepository(session).count_for_tournament(tournament_id)

    async def delete_all_for_tournament_in_session(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> int:
        return await TournamentPhotoRepository(session).delete_all_for_tournament(tournament_id)

    async def _require_editable_tournament_for_actor(
        self,
        session: AsyncSession,
        tournament_id: int,
        *,
        actor_role: object,
    ) -> Tournament:
        tournament = await TournamentRepository(session).get_by_id(tournament_id)
        if tournament is None:
            raise ResultTournamentNotFoundError
        if not can_edit_open_tournament_for_actor(
            actor_role=actor_role,
            tournament_status=tournament.status,
            tournament_date=tournament.date,
            business_date=self._tournament_day(),
            admin_current_day_only=False,
        ):
            raise TournamentResultsEditingUnavailableError
        return tournament

    def _tournament_day(self) -> date:
        return resolve_tournament_day(self.clock, self.tournament_day_start_hour)


tournament_photo_service = TournamentPhotoService(SessionFactory)
