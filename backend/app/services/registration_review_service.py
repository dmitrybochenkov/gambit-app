from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.clock import Clock, club_clock
from app.db.factories import create_user
from app.db.models import RegistrationRequest, User
from app.db.models.enums import RegistrationRequestStatus, RegistrationRequestType, UserStatus
from app.db.repositories.registration_request_repository import RegistrationRequestRepository
from app.db.repositories.user_repository import UserRepository
from app.db.session import SessionFactory
from app.services.access_policy import access_policy
from app.services.dto.registrations import (
    RegistrationNotificationView,
    RegistrationReviewResultView,
    RegistrationReviewView,
)
from app.services.registration_service import find_link_candidates
from app.services.user_common import (
    RegistrationAlreadyReviewedError,
    RegistrationCandidateNotFoundError,
    RegistrationNotAllowedError,
    RegistrationRequestNotFoundError,
    require_valid_display_name,
    required_registration_request_view,
    required_user_view,
)


class RegistrationReviewService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Clock = club_clock,
    ) -> None:
        self.session_factory = session_factory
        self.clock = clock

    async def get_registration_notification(
        self,
        request_id: int,
    ) -> RegistrationNotificationView:
        async with self.session_factory() as session:
            user_repository = UserRepository(session)
            request = await RegistrationRequestRepository(session).get_by_id(request_id)
            if request is None:
                raise RegistrationRequestNotFoundError
            return RegistrationNotificationView(
                request=required_registration_request_view(request),
                admins=[
                    required_user_view(user)
                    for user in await user_repository.list_active_superadmins_with_telegram()
                ],
                candidates=await self._registration_candidates(user_repository, request),
            )

    async def list_pending_reviews_for_superadmin(
        self,
        superadmin_telegram_id: int,
    ) -> list[RegistrationReviewView]:
        async with self.session_factory() as session:
            user_repository = UserRepository(session)
            request_repository = RegistrationRequestRepository(session)
            await access_policy.require_superadmin(session, superadmin_telegram_id)
            return [
                await self._registration_review_view(user_repository, request)
                for request in await request_repository.list_pending()
            ]

    async def get_registration_review_for_admin(
        self,
        admin_telegram_id: int,
        request_id: int,
    ) -> RegistrationReviewView:
        async with self.session_factory() as session:
            user_repository = UserRepository(session)
            await access_policy.require_superadmin(session, admin_telegram_id)
            request = await self._require_pending_request(
                RegistrationRequestRepository(session),
                request_id,
            )
            return await self._registration_review_view(user_repository, request)

    async def update_registration_display_name(
        self,
        superadmin_telegram_id: int,
        request_id: int,
        display_name: str,
    ) -> RegistrationReviewView:
        display_name_normalized = require_valid_display_name(display_name)
        async with self.session_factory() as session:
            user_repository = UserRepository(session)
            request_repository = RegistrationRequestRepository(session)
            await access_policy.require_superadmin(session, superadmin_telegram_id)
            request = await self._require_pending_request(request_repository, request_id)
            if request.request_type != RegistrationRequestType.NEW_PLAYER:
                raise RegistrationRequestNotFoundError
            request.requested_display_name = display_name
            request.requested_display_name_normalized = display_name_normalized
            await session.commit()
            await session.refresh(request)
            return await self._registration_review_view(user_repository, request)

    async def select_registration_candidate(
        self,
        superadmin_telegram_id: int,
        request_id: int,
        user_id: int,
    ) -> RegistrationReviewView:
        async with self.session_factory() as session:
            user_repository = UserRepository(session)
            request_repository = RegistrationRequestRepository(session)
            await access_policy.require_superadmin(session, superadmin_telegram_id)
            request = await self._require_pending_request(request_repository, request_id)
            candidate = await self._require_link_candidate(user_repository, user_id)
            request.candidate_user_id = candidate.id
            await session.commit()
            await session.refresh(request)
            return await self._registration_review_view(user_repository, request)

    async def approve_registration(
        self,
        superadmin_telegram_id: int,
        request_id: int,
    ) -> RegistrationReviewResultView:
        async with self.session_factory() as session:
            user_repository = UserRepository(session)
            request_repository = RegistrationRequestRepository(session)
            await access_policy.require_superadmin(session, superadmin_telegram_id)
            request = await self._require_pending_request(request_repository, request_id)
            admins = await user_repository.list_active_admins()
            if await user_repository.get_by_telegram_id(request.telegram_id) is not None:
                raise RegistrationNotAllowedError

            if request.request_type == RegistrationRequestType.NEW_PLAYER:
                if (
                    not request.requested_display_name
                    or not request.requested_display_name_normalized
                ):
                    raise RegistrationRequestNotFoundError
                user = create_user(
                    telegram_id=request.telegram_id,
                    display_name=request.requested_display_name,
                )
                user_repository.add(user)
                request.status = RegistrationRequestStatus.APPROVED
                request.reviewed_at = self.clock.now()
                try:
                    await session.commit()
                except IntegrityError as exc:
                    await session.rollback()
                    raise RegistrationNotAllowedError from exc
                await session.refresh(user)
            else:
                if request.candidate_user_id is None:
                    raise RegistrationCandidateNotFoundError
                user = await self._require_link_candidate(
                    user_repository,
                    request.candidate_user_id,
                )
                user.telegram_id = request.telegram_id
                request.status = RegistrationRequestStatus.APPROVED
                request.reviewed_at = self.clock.now()
                try:
                    await session.commit()
                except IntegrityError as exc:
                    await session.rollback()
                    raise RegistrationNotAllowedError from exc
                await session.refresh(user)

            await session.refresh(request)
            return RegistrationReviewResultView(
                user=required_user_view(user),
                request=required_registration_request_view(request),
                admins=[required_user_view(admin) for admin in admins],
            )

    async def reject_registration(
        self,
        superadmin_telegram_id: int,
        request_id: int,
    ) -> RegistrationReviewResultView:
        async with self.session_factory() as session:
            user_repository = UserRepository(session)
            request_repository = RegistrationRequestRepository(session)
            await access_policy.require_superadmin(session, superadmin_telegram_id)
            request = await self._require_pending_request(request_repository, request_id)
            admins = await user_repository.list_active_admins()
            request.status = RegistrationRequestStatus.REJECTED
            request.reviewed_at = self.clock.now()
            await session.commit()
            await session.refresh(request)
            return RegistrationReviewResultView(
                user=None,
                request=required_registration_request_view(request),
                admins=[required_user_view(admin) for admin in admins],
            )

    @staticmethod
    async def _registration_review_view(
        user_repository: UserRepository,
        request: RegistrationRequest,
    ) -> RegistrationReviewView:
        return RegistrationReviewView(
            request=required_registration_request_view(request),
            candidates=await RegistrationReviewService._registration_candidates(
                user_repository,
                request,
            ),
        )

    @staticmethod
    async def _registration_candidates(
        user_repository: UserRepository,
        request: RegistrationRequest,
    ):
        if request.request_type != RegistrationRequestType.LINK_EXISTING_PLAYER:
            return []
        return await find_link_candidates(
            user_repository=user_repository,
            requested_link_name=request.requested_link_name or "",
        )

    @staticmethod
    async def _require_pending_request(
        repository: RegistrationRequestRepository,
        request_id: int,
    ) -> RegistrationRequest:
        request = await repository.get_by_id(request_id)
        if request is None:
            raise RegistrationRequestNotFoundError
        if request.status != RegistrationRequestStatus.PENDING:
            raise RegistrationAlreadyReviewedError
        return request

    @staticmethod
    async def _require_link_candidate(repository: UserRepository, user_id: int) -> User:
        user = await repository.get_by_id(user_id)
        if user is None or user.status != UserStatus.ACTIVE or user.telegram_id is not None:
            raise RegistrationCandidateNotFoundError
        return user


registration_review_service = RegistrationReviewService(SessionFactory)
