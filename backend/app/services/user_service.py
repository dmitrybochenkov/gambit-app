from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.clock import Clock, club_clock
from app.common.normalization import normalize_display_name
from app.db.factories import create_user
from app.db.models import RegistrationRequest, User
from app.db.models.enums import (
    RegistrationRequestStatus,
    RegistrationRequestType,
    UserRole,
    UserStatus,
)
from app.db.repositories.registration_request_repository import (
    RegistrationRequestRepository,
)
from app.db.repositories.user_repository import UserRepository
from app.db.session import SessionFactory
from app.services.access_policy import (
    ActiveUserRequiredError,  # noqa: F401
    AdminAccessDeniedError,  # noqa: F401
    access_policy,
)
from app.services.dto import (
    AdminPanelView,
    RegistrationCandidateView,
    RegistrationNotificationView,
    RegistrationRequestView,
    RegistrationReviewResultView,
    RegistrationReviewView,
    UserRoleView,
    UserStartView,
    UserStatusView,
    UserView,
)
from app.services.player_search import (
    InvalidDisplayNameError as InvalidDisplayNameError,
)
from app.services.player_search import (
    PlayerSearchCandidate,
    rank_player_candidates,
    validate_display_name,
)


class IdentityAlreadyExistsError(ValueError):
    def __init__(self, field: str) -> None:
        self.field = field
        super().__init__(f"{field} already exists")


class RegistrationNotAllowedError(ValueError):
    pass


class RegistrationRequestNotFoundError(ValueError):
    pass


class RegistrationAlreadyReviewedError(ValueError):
    pass


class UserNotFoundError(ValueError):
    pass


class RegistrationCandidateNotFoundError(ValueError):
    pass


class UserRoleAlreadyAssignedError(ValueError):
    pass


class UserService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Clock = club_clock,
    ) -> None:
        self.session_factory = session_factory
        self.clock = clock

    async def get_by_telegram_id(self, telegram_id: int) -> UserView | None:
        async with self.session_factory() as session:
            user = await UserRepository(session).get_by_telegram_id(telegram_id)
            return user_view(user)

    async def get_start_view(self, telegram_id: int) -> UserStartView:
        async with self.session_factory() as session:
            user = await UserRepository(session).get_by_telegram_id(telegram_id)
            if user is not None:
                user_view = required_user_view(user)
                if user.status == UserStatus.BLOCKED:
                    return UserStartView.blocked(user_view)
                return UserStartView.registered(user_view)

            request = await RegistrationRequestRepository(session).get_pending_by_telegram_id(
                telegram_id
            )
            return (
                UserStartView.pending_registration()
                if request is not None
                else UserStartView.needs_registration()
            )

    async def require_active_user(self, telegram_id: int) -> UserView:
        async with self.session_factory() as session:
            user = await require_active_user(UserRepository(session), telegram_id)
            return required_user_view(user)

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
        display_name_normalized = _require_valid_display_name(display_name)
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
        display_name_normalized = _require_valid_display_name(display_name)
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
        requested_link_name = _require_valid_display_name(requested_link_name)
        async with self.session_factory() as session:
            user_repository = UserRepository(session)
            request_repository = RegistrationRequestRepository(session)
            if await user_repository.get_by_telegram_id(telegram_id) is not None:
                raise RegistrationNotAllowedError
            if await request_repository.get_pending_by_telegram_id(telegram_id) is not None:
                raise RegistrationNotAllowedError
            if not await self._find_link_candidates(
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

    async def get_active_admins(self) -> list[UserView]:
        async with self.session_factory() as session:
            users = await UserRepository(session).list_active_admins()
            return [required_user_view(user) for user in users]

    async def get_admin_panel_for_admin(
        self,
        admin_telegram_id: int,
    ) -> AdminPanelView:
        async with self.session_factory() as session:
            user_repository = UserRepository(session)
            request_repository = RegistrationRequestRepository(session)
            admin = await self._require_admin(user_repository, admin_telegram_id)
            reviews = [
                await self._registration_review_view(user_repository, request)
                for request in await request_repository.list_pending()
            ]
            return AdminPanelView(
                admin=required_user_view(admin),
                reviews=reviews,
            )

    async def require_superadmin(self, telegram_id: int) -> UserView:
        async with self.session_factory() as session:
            user = await self._require_superadmin(UserRepository(session), telegram_id)
            return required_user_view(user)

    async def list_admin_candidates_for_superadmin(
        self,
        superadmin_telegram_id: int,
    ) -> list[UserView]:
        async with self.session_factory() as session:
            repository = UserRepository(session)
            await self._require_superadmin(repository, superadmin_telegram_id)
            users = await repository.list_admin_candidates()
            return [required_user_view(user) for user in users]

    async def add_admin(
        self,
        superadmin_telegram_id: int,
        user_id: int,
    ) -> UserView:
        async with self.session_factory() as session:
            repository = UserRepository(session)
            await self._require_superadmin(repository, superadmin_telegram_id)
            user = await repository.get_by_id(user_id)
            if user is None or user.status != UserStatus.ACTIVE:
                raise UserNotFoundError
            if user.role != UserRole.PLAYER:
                raise UserRoleAlreadyAssignedError

            user.role = UserRole.ADMIN
            await session.commit()
            await session.refresh(user)
            return required_user_view(user)

    async def create_manual_player(
        self,
        admin_telegram_id: int,
        display_name: str,
    ) -> UserView:
        _require_valid_display_name(display_name)
        async with self.session_factory() as session:
            user_repository = UserRepository(session)
            await self._require_admin(user_repository, admin_telegram_id)
            user = create_user(display_name=display_name)
            user_repository.add(user)
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise IdentityAlreadyExistsError("display_name") from exc
            await session.refresh(user)
            return required_user_view(user)

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
                    required_user_view(user) for user in await user_repository.list_active_admins()
                ],
                candidates=await self._registration_candidates(user_repository, request),
            )

    async def get_registration_review_for_admin(
        self,
        admin_telegram_id: int,
        request_id: int,
    ) -> RegistrationReviewView:
        async with self.session_factory() as session:
            user_repository = UserRepository(session)
            await self._require_superadmin(user_repository, admin_telegram_id)
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
        display_name_normalized = _require_valid_display_name(display_name)
        async with self.session_factory() as session:
            user_repository = UserRepository(session)
            request_repository = RegistrationRequestRepository(session)
            await self._require_superadmin(user_repository, superadmin_telegram_id)
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
            await self._require_superadmin(user_repository, superadmin_telegram_id)
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
            await self._require_superadmin(user_repository, superadmin_telegram_id)
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
        rejection_reason: str | None = None,
    ) -> RegistrationReviewResultView:
        async with self.session_factory() as session:
            user_repository = UserRepository(session)
            request_repository = RegistrationRequestRepository(session)
            await self._require_superadmin(user_repository, superadmin_telegram_id)
            request = await self._require_pending_request(request_repository, request_id)
            admins = await user_repository.list_active_admins()
            request.status = RegistrationRequestStatus.REJECTED
            request.rejection_reason = rejection_reason
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
            candidates=await UserService._registration_candidates(user_repository, request),
        )

    @staticmethod
    async def _registration_candidates(
        user_repository: UserRepository,
        request: RegistrationRequest,
    ) -> list[RegistrationCandidateView]:
        if request.request_type != RegistrationRequestType.LINK_EXISTING_PLAYER:
            return []
        return await UserService._find_link_candidates(
            user_repository=user_repository,
            requested_link_name=request.requested_link_name or "",
        )

    @staticmethod
    async def _find_link_candidates(
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
                score=_registration_candidate_score(candidate),
                reason=candidate.reason,
            )
            for candidate in candidates
        ]

    @staticmethod
    async def _ensure_public_registration_name_available(
        *,
        session: AsyncSession,
        display_name_normalized: str,
    ) -> None:
        users = await UserRepository(session).list_by_display_name_normalized(
            display_name_normalized
        )
        if users:
            raise IdentityAlreadyExistsError("display_name")

    @staticmethod
    async def _require_admin(repository: UserRepository, telegram_id: int) -> User:
        return await access_policy.require_admin(repository.session, telegram_id)

    @staticmethod
    async def _require_superadmin(repository: UserRepository, telegram_id: int) -> User:
        return await access_policy.require_superadmin(repository.session, telegram_id)

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
        if (
            user is None
            or user.role != UserRole.PLAYER
            or user.status != UserStatus.ACTIVE
            or user.telegram_id is not None
        ):
            raise RegistrationCandidateNotFoundError
        return user


user_service = UserService(SessionFactory)


async def require_active_user(repository: UserRepository, telegram_id: int) -> User:
    return await access_policy.require_active_user(repository.session, telegram_id)


def user_view(user: User | None) -> UserView | None:
    if user is None:
        return None
    return required_user_view(user)


def required_user_view(user: User) -> UserView:
    return UserView(
        id=user.id,
        telegram_id=user.telegram_id,
        display_name=user.display_name,
        status=UserStatusView(user.status.value),
        role=UserRoleView(user.role.value),
    )


def registration_request_view(
    request: RegistrationRequest | None,
) -> RegistrationRequestView | None:
    if request is None:
        return None
    return required_registration_request_view(request)


def required_registration_request_view(
    request: RegistrationRequest,
) -> RegistrationRequestView:
    return RegistrationRequestView(
        id=request.id,
        telegram_id=request.telegram_id,
        request_type=request.request_type.value,
        status=request.status.value,
        requested_display_name=request.requested_display_name,
        requested_link_name=request.requested_link_name,
        candidate_user_id=request.candidate_user_id,
        created_at=request.created_at.strftime("%d.%m.%Y %H:%M"),
    )


def _require_valid_display_name(display_name: str) -> str:
    return validate_display_name(display_name)


def _registration_candidate_score(candidate: PlayerSearchCandidate) -> int:
    if candidate.score == 300:
        return 100
    if candidate.reason == "имя игрока частично совпадает":
        return 95
    return candidate.score
