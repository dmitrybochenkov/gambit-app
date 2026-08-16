from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.clock import Clock, club_clock
from app.config import settings
from app.db.factories import create_user
from app.db.models import RegistrationRequest, User
from app.db.models.enums import RegistrationRequestStatus, RegistrationRequestType, UserStatus
from app.db.repositories.registration_request_repository import RegistrationRequestRepository
from app.db.repositories.tournament_registration_repository import TournamentRegistrationRepository
from app.db.repositories.user_repository import UserRepository
from app.db.session import SessionFactory
from app.domain.tournament_day import resolve_tournament_day
from app.services.access_policy import access_policy
from app.services.dto.registrations import (
    RegistrationCandidateView,
    RegistrationNotificationView,
    RegistrationReviewResultView,
    RegistrationReviewView,
    RegistrationsOverviewView,
    TournamentRegistrationCountView,
)
from app.services.pagination import Page
from app.services.registration_service import RegistrationService, find_link_candidates
from app.services.user_common import (
    RegistrationAlreadyReviewedError,
    RegistrationCandidateNotFoundError,
    RegistrationNotAllowedError,
    RegistrationRequestNotFoundError,
    required_registration_request_view,
    required_user_view,
)


class RegistrationReviewService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Clock = club_clock,
        tournament_day_start_hour: int = settings.tournament_day_start_hour,
    ) -> None:
        self.session_factory = session_factory
        self.clock = clock
        self.tournament_day_start_hour = tournament_day_start_hour

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

    async def list_pending_reviews_page_for_superadmin(
        self,
        superadmin_telegram_id: int,
        *,
        page: int,
        page_size: int,
    ) -> Page[RegistrationReviewView]:
        async with self.session_factory() as session:
            user_repository = UserRepository(session)
            request_repository = RegistrationRequestRepository(session)
            await access_policy.require_superadmin(session, superadmin_telegram_id)
            total_items = await request_repository.count_pending()
            normalized_page = self._normalize_page(
                page=page,
                page_size=page_size,
                total_items=total_items,
            )
            requests = await request_repository.list_pending_page(
                limit=page_size,
                offset=normalized_page * page_size,
            )
            return Page(
                items=[
                    await self._registration_review_view(user_repository, request)
                    for request in requests
                ],
                page=normalized_page,
                page_size=page_size,
                total_items=total_items,
            )

    async def get_registrations_overview_for_superadmin(
        self,
        superadmin_telegram_id: int,
    ) -> RegistrationsOverviewView:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, superadmin_telegram_id)
            request_repository = RegistrationRequestRepository(session)
            tournament_registrations = TournamentRegistrationRepository(session)
            tournaments = await tournament_registrations.list_active_tournament_registration_counts(
                from_date=resolve_tournament_day(
                    self.clock,
                    self.tournament_day_start_hour,
                ),
            )
            return RegistrationsOverviewView(
                pending_user_registration_count=await request_repository.count_pending(),
                active_tournament_registration_count=sum(
                    row.registrations_count for row in tournaments
                ),
                tournaments=[
                    TournamentRegistrationCountView(
                        tournament_id=row.tournament_id,
                        date=row.tournament_date,
                        tournament_type_name=row.tournament_type_name,
                        registrations_count=row.registrations_count,
                    )
                    for row in tournaments
                ],
            )

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
            return await self._registration_review_view(
                user_repository,
                request,
                selected_user_id=user_id,
            )

    async def approve_registration(
        self,
        superadmin_telegram_id: int,
        request_id: int,
        candidate_user_id: int | None = None,
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
                await RegistrationService._ensure_public_registration_name_available(
                    session=session,
                    display_name_normalized=request.requested_display_name_normalized,
                )
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
                user = await self._resolve_link_candidate_for_approval(
                    user_repository,
                    request,
                    candidate_user_id,
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
        selected_user_id: int | None = None,
    ) -> RegistrationReviewView:
        candidates = await RegistrationReviewService._registration_candidates(
            user_repository,
            request,
        )
        selected_candidate = RegistrationReviewService._selected_candidate(
            candidates,
            selected_user_id if selected_user_id is not None else request.candidate_user_id,
        )
        if selected_user_id is not None and selected_candidate is None:
            raise RegistrationCandidateNotFoundError
        return RegistrationReviewView(
            request=required_registration_request_view(request),
            candidates=candidates,
            selected_candidate=selected_candidate,
        )

    @staticmethod
    async def _registration_candidates(
        user_repository: UserRepository,
        request: RegistrationRequest,
    ) -> list[RegistrationCandidateView]:
        if request.request_type != RegistrationRequestType.LINK_EXISTING_PLAYER:
            return []
        return await find_link_candidates(
            user_repository=user_repository,
            requested_link_name=request.requested_link_name or "",
        )

    @staticmethod
    def _selected_candidate(
        candidates: list[RegistrationCandidateView],
        selected_user_id: int | None,
    ) -> RegistrationCandidateView | None:
        if selected_user_id is None:
            return None
        return next(
            (candidate for candidate in candidates if candidate.user.id == selected_user_id),
            None,
        )

    @staticmethod
    async def _resolve_link_candidate_for_approval(
        user_repository: UserRepository,
        request: RegistrationRequest,
        candidate_user_id: int | None,
    ) -> User:
        candidates = await RegistrationReviewService._registration_candidates(
            user_repository,
            request,
        )
        selected_user_id = candidate_user_id or request.candidate_user_id
        if selected_user_id is None:
            if len(candidates) != 1:
                raise RegistrationCandidateNotFoundError
            selected_user_id = candidates[0].user.id
        elif selected_user_id not in {candidate.user.id for candidate in candidates}:
            raise RegistrationCandidateNotFoundError

        return await RegistrationReviewService._require_link_candidate(
            user_repository,
            selected_user_id,
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
    def _normalize_page(*, page: int, page_size: int, total_items: int) -> int:
        if page_size < 1:
            raise ValueError("page_size must be positive")
        if total_items <= 0:
            return 0
        total_pages = (total_items + page_size - 1) // page_size
        return min(max(0, page), total_pages - 1)

    @staticmethod
    async def _require_link_candidate(repository: UserRepository, user_id: int) -> User:
        user = await repository.get_by_id(user_id)
        if user is None or user.status != UserStatus.ACTIVE or user.telegram_id is not None:
            raise RegistrationCandidateNotFoundError
        return user


registration_review_service = RegistrationReviewService(SessionFactory)
