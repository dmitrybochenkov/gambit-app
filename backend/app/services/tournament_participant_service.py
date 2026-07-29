from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.factories import create_user
from app.db.models import RegistrationRequest, TournamentResultDraft
from app.db.models.enums import (
    RegistrationRequestStatus,
    RegistrationRequestType,
    TournamentParticipantSource,
    TournamentStatus,
    UserRole,
    UserStatus,
)
from app.db.repositories.tournament_participant_repository import (
    TournamentParticipantRepository,
)
from app.db.repositories.tournament_repository import TournamentRepository
from app.db.repositories.user_repository import UserRepository
from app.db.session import SessionFactory
from app.services.dto import (
    TournamentCheckInPlayerView,
    TournamentCheckInView,
    UserView,
)
from app.services.tournament_service import _player_search_score, tournament_view
from app.services.user_service import (
    AdminAccessDeniedError,
    IdentityAlreadyExistsError,
    _require_valid_display_name,
    required_user_view,
)


class TournamentCheckInNotFoundError(ValueError):
    pass


class TournamentCheckInClosedError(ValueError):
    pass


class TournamentCheckInUserNotFoundError(ValueError):
    pass


class TournamentCheckInAlreadyExistsError(ValueError):
    pass


class TournamentCheckInRegistrationNotFoundError(ValueError):
    pass


class TournamentCheckInHasResultError(ValueError):
    pass


class TournamentParticipantService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def get_check_in(
        self,
        admin_telegram_id: int,
        tournament_id: int,
    ) -> TournamentCheckInView:
        async with self.session_factory() as session:
            await self._require_admin(session, admin_telegram_id)
            tournament = await self._require_open_tournament(session, tournament_id)
            return await self._check_in_view(session, tournament.id)

    async def toggle_registered(
        self,
        admin_telegram_id: int,
        tournament_id: int,
        user_id: int,
    ) -> TournamentCheckInView:
        async with self.session_factory() as session:
            admin = await self._require_admin(session, admin_telegram_id)
            tournament = await self._require_open_tournament(session, tournament_id)
            repository = TournamentParticipantRepository(session)
            registered_ids = await repository.registered_user_ids(tournament.id)
            if user_id not in registered_ids:
                raise TournamentCheckInRegistrationNotFoundError

            participant = await repository.get(tournament.id, user_id)
            if participant is None:
                await self._check_in_user(
                    session=session,
                    tournament_id=tournament.id,
                    user_id=user_id,
                    source=TournamentParticipantSource.PRE_REGISTERED,
                    checked_in_by_user_id=admin.id,
                )
            else:
                await self._remove_participant(session, tournament.id, user_id)
            await session.commit()
            return await self._check_in_view(session, tournament.id)

    async def check_in_existing_user(
        self,
        admin_telegram_id: int,
        tournament_id: int,
        user_id: int,
    ) -> TournamentCheckInView:
        async with self.session_factory() as session:
            admin = await self._require_admin(session, admin_telegram_id)
            tournament = await self._require_open_tournament(session, tournament_id)
            user = await UserRepository(session).get_by_id(user_id)
            if user is None or user.status != UserStatus.ACTIVE or user.role != UserRole.PLAYER:
                raise TournamentCheckInUserNotFoundError

            registered_ids = await TournamentParticipantRepository(session).registered_user_ids(
                tournament.id
            )
            source = (
                TournamentParticipantSource.PRE_REGISTERED
                if user.id in registered_ids
                else TournamentParticipantSource.DATABASE_WALK_IN
            )
            await self._check_in_user(
                session=session,
                tournament_id=tournament.id,
                user_id=user.id,
                source=source,
                checked_in_by_user_id=admin.id,
            )
            await session.commit()
            return await self._check_in_view(session, tournament.id)

    async def create_user_and_check_in(
        self,
        admin_telegram_id: int,
        tournament_id: int,
        display_name: str,
    ) -> TournamentCheckInView:
        _require_valid_display_name(display_name)
        async with self.session_factory() as session:
            admin = await self._require_admin(session, admin_telegram_id)
            tournament = await self._require_open_tournament(session, tournament_id)
            user = create_user(display_name=display_name)
            session.add(user)
            try:
                await session.flush()
                session.add(
                    RegistrationRequest(
                        telegram_id=None,
                        request_type=RegistrationRequestType.ADMIN_CREATED_PLAYER_REVIEW,
                        status=RegistrationRequestStatus.PENDING,
                        subject_user_id=user.id,
                        created_by_user_id=admin.id,
                        tournament_id=tournament.id,
                    )
                )
                await self._check_in_user(
                    session=session,
                    tournament_id=tournament.id,
                    user_id=user.id,
                    source=TournamentParticipantSource.ADMIN_CREATED,
                    checked_in_by_user_id=admin.id,
                )
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise IdentityAlreadyExistsError("display_name") from exc
            return await self._check_in_view(session, tournament.id)

    async def search_registered(
        self,
        admin_telegram_id: int,
        tournament_id: int,
        query: str,
    ) -> list[TournamentCheckInPlayerView]:
        async with self.session_factory() as session:
            await self._require_admin(session, admin_telegram_id)
            tournament = await self._require_open_tournament(session, tournament_id)
            repository = TournamentParticipantRepository(session)
            participant_ids = set(await repository.list_user_ids(tournament.id))
            players = await repository.search_registered(tournament.id)
            scored = [
                (score, player)
                for player in players
                if (score := _player_search_score(player, query)) > 0
            ]
            scored.sort(key=lambda item: (-item[0], item[1].display_name.casefold(), item[1].id))
            return [
                TournamentCheckInPlayerView(
                    user_id=player.id,
                    display_name=player.display_name,
                    is_pre_registered=True,
                    is_checked_in=player.id in participant_ids,
                )
                for _, player in scored[:10]
            ]

    async def search_users(
        self,
        admin_telegram_id: int,
        tournament_id: int,
        query: str,
    ) -> list[UserView]:
        async with self.session_factory() as session:
            await self._require_admin(session, admin_telegram_id)
            await self._require_open_tournament(session, tournament_id)
            participant_ids = set(
                await TournamentParticipantRepository(session).list_user_ids(tournament_id)
            )
            users = await UserRepository(session).list_active_players()
            scored = [
                (score, user)
                for user in users
                if user.id not in participant_ids
                and (score := _player_search_score(user, query)) > 0
            ]
            scored.sort(key=lambda item: (-item[0], item[1].display_name.casefold(), item[1].id))
            return [required_user_view(user) for _, user in scored[:10]]

    @staticmethod
    async def _require_admin(session: AsyncSession, telegram_id: int):
        admin = await UserRepository(session).get_by_telegram_id(telegram_id)
        if (
            admin is None
            or admin.status != UserStatus.ACTIVE
            or admin.role not in {UserRole.ADMIN, UserRole.SUPERADMIN}
        ):
            raise AdminAccessDeniedError
        return admin

    @staticmethod
    async def _require_open_tournament(session: AsyncSession, tournament_id: int):
        tournament = await TournamentRepository(session).get_by_id(tournament_id)
        if tournament is None:
            raise TournamentCheckInNotFoundError
        if tournament.status != TournamentStatus.ACTIVE or tournament.date > date.today():
            raise TournamentCheckInClosedError
        return tournament

    @staticmethod
    async def _check_in_user(
        *,
        session: AsyncSession,
        tournament_id: int,
        user_id: int,
        source: TournamentParticipantSource,
        checked_in_by_user_id: int,
    ) -> None:
        repository = TournamentParticipantRepository(session)
        await repository.add_if_missing(
            tournament_id=tournament_id,
            user_id=user_id,
            source=source,
            checked_in_by_user_id=checked_in_by_user_id,
        )
        if not await _draft_exists(session, tournament_id, user_id):
            session.add(
                TournamentResultDraft(
                    tournament_id=tournament_id,
                    player_id=user_id,
                    place=None,
                    knockouts_count=0,
                    big_knockouts_count=0,
                )
            )
        await session.flush()

    @staticmethod
    async def _remove_participant(
        session: AsyncSession,
        tournament_id: int,
        user_id: int,
    ) -> None:
        repository = TournamentParticipantRepository(session)
        if await repository.has_result_data(tournament_id, user_id):
            raise TournamentCheckInHasResultError
        participant = await repository.get(tournament_id, user_id)
        if participant is not None:
            await repository.delete(participant)
        await repository.delete_empty_draft(tournament_id, user_id)
        await session.flush()

    @staticmethod
    async def _check_in_view(
        session: AsyncSession,
        tournament_id: int,
    ) -> TournamentCheckInView:
        tournament = await TournamentRepository(session).get_by_id(tournament_id)
        if tournament is None:
            raise TournamentCheckInNotFoundError
        repository = TournamentParticipantRepository(session)
        rows = await repository.list_registered_check_in_rows(tournament_id)
        participant_count = await repository.participant_count(tournament_id)
        walk_in_count = await repository.walk_in_count(tournament_id)
        players = [
            TournamentCheckInPlayerView(
                user_id=row.user_id,
                display_name=row.display_name,
                is_pre_registered=True,
                is_checked_in=row.source is not None,
                source=row.source.value if row.source is not None else None,
                has_result_data=(
                    row.place is not None or row.knockouts_count > 0 or row.big_knockouts_count > 0
                ),
            )
            for row in rows
        ]
        registered_count = len(players)
        checked_registered_count = sum(1 for player in players if player.is_checked_in)
        return TournamentCheckInView(
            tournament=tournament_view(tournament),
            registered_count=registered_count,
            participant_count=participant_count,
            unchecked_registered_count=registered_count - checked_registered_count,
            walk_in_count=walk_in_count,
            players=players,
        )


async def _draft_exists(session: AsyncSession, tournament_id: int, user_id: int) -> bool:
    result = await session.execute(
        select(TournamentResultDraft.id).where(
            TournamentResultDraft.tournament_id == tournament_id,
            TournamentResultDraft.player_id == user_id,
        )
    )
    return result.scalar_one_or_none() is not None


tournament_participant_service = TournamentParticipantService(SessionFactory)
