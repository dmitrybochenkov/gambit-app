from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.normalization import normalize_display_name
from app.db.models import RegistrationRequest
from app.db.models.enums import RegistrationRequestStatus, RegistrationRequestType
from app.db.repositories.registration_request_repository import RegistrationRequestRepository
from app.db.repositories.user_repository import UserRepository
from app.db.session import SessionFactory
from app.services.dto.registrations import RegistrationCandidateView, RegistrationRequestView
from app.services.player_search import rank_player_candidates
from app.services.user_common import (
    DisplayNameHistoricalUserExistsError,
    DisplayNameLinkedUserExistsError,
    RegistrationCandidateNotFoundError,
    RegistrationNotAllowedError,
    registration_candidate_score,
    registration_request_view,
    require_valid_display_name,
    required_registration_request_view,
    required_user_view,
)


class RegistrationService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def get_pending_registration_by_telegram_id(
        self,
        telegram_id: int,
    ) -> RegistrationRequestView | None:
        async with self.session_factory() as session:
            request = await RegistrationRequestRepository(session).get_pending_by_telegram_id(
                telegram_id
            )
            return registration_request_view(request)

    async def validate_new_player_display_name(
        self,
        display_name: str,
        exclude_request_id: int | None = None,
    ) -> None:
        del exclude_request_id
        display_name_normalized = require_valid_display_name(display_name)
        async with self.session_factory() as session:
            await self._ensure_public_registration_name_available(
                session=session,
                display_name_normalized=display_name_normalized,
            )

    async def submit_new_player_registration(
        self,
        telegram_id: int,
        display_name: str,
    ) -> RegistrationRequestView:
        display_name_normalized = require_valid_display_name(display_name)
        async with self.session_factory() as session:
            user_repository = UserRepository(session)
            request_repository = RegistrationRequestRepository(session)
            if await user_repository.get_by_telegram_id(telegram_id) is not None:
                raise RegistrationNotAllowedError
            if await request_repository.get_pending_by_telegram_id(telegram_id) is not None:
                raise RegistrationNotAllowedError
            await self._ensure_public_registration_name_available(
                session=session,
                display_name_normalized=display_name_normalized,
            )
            request = RegistrationRequest(
                telegram_id=telegram_id,
                request_type=RegistrationRequestType.NEW_PLAYER,
                status=RegistrationRequestStatus.PENDING,
                requested_display_name=display_name,
                requested_display_name_normalized=display_name_normalized,
            )
            request_repository.add(request)
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise RegistrationNotAllowedError from exc
            await session.refresh(request)
            return required_registration_request_view(request)

    async def submit_link_existing_registration(
        self,
        telegram_id: int,
        requested_link_name: str,
    ) -> RegistrationRequestView:
        requested_link_name = require_valid_display_name(requested_link_name)
        async with self.session_factory() as session:
            user_repository = UserRepository(session)
            request_repository = RegistrationRequestRepository(session)
            if await user_repository.get_by_telegram_id(telegram_id) is not None:
                raise RegistrationNotAllowedError
            if await request_repository.get_pending_by_telegram_id(telegram_id) is not None:
                raise RegistrationNotAllowedError
            if not await find_link_candidates(
                user_repository=user_repository,
                requested_link_name=requested_link_name,
            ):
                raise RegistrationCandidateNotFoundError

            request = RegistrationRequest(
                telegram_id=telegram_id,
                request_type=RegistrationRequestType.LINK_EXISTING_PLAYER,
                status=RegistrationRequestStatus.PENDING,
                requested_link_name=requested_link_name,
            )
            request_repository.add(request)
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise RegistrationNotAllowedError from exc
            await session.refresh(request)
            return required_registration_request_view(request)

    @staticmethod
    async def _ensure_public_registration_name_available(
        *,
        session: AsyncSession,
        display_name_normalized: str,
    ) -> None:
        users = await UserRepository(session).list_by_display_name_normalized(
            display_name_normalized
        )
        if not users:
            return
        if any(user.telegram_id is not None for user in users):
            raise DisplayNameLinkedUserExistsError("display_name")
        raise DisplayNameHistoricalUserExistsError("display_name")


async def find_link_candidates(
    user_repository: UserRepository,
    requested_link_name: str,
) -> list[RegistrationCandidateView]:
    normalized = normalize_display_name(requested_link_name)
    if normalized is None:
        return []
    candidates = rank_player_candidates(
        await user_repository.list_link_candidates(),
        requested_link_name,
        limit=6,
    )
    return [
        RegistrationCandidateView(
            user=required_user_view(candidate.user),
            score=registration_candidate_score(candidate),
            reason=candidate.reason,
        )
        for candidate in candidates
    ]


registration_service = RegistrationService(SessionFactory)
