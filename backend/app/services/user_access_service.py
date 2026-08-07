from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models.enums import UserStatus
from app.db.repositories.registration_request_repository import RegistrationRequestRepository
from app.db.repositories.user_repository import UserRepository
from app.db.session import SessionFactory
from app.services.access_policy import access_policy
from app.services.dto.registrations import AdminPanelView
from app.services.dto.users import UserStartView, UserView
from app.services.user_common import required_user_view, user_view


class UserAccessService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def get_by_telegram_id(self, telegram_id: int) -> UserView | None:
        async with self.session_factory() as session:
            user = await UserRepository(session).get_by_telegram_id(telegram_id)
            return user_view(user)

    async def get_start_view(self, telegram_id: int) -> UserStartView:
        async with self.session_factory() as session:
            user = await UserRepository(session).get_by_telegram_id(telegram_id)
            if user is not None:
                view = required_user_view(user)
                if user.status == UserStatus.BLOCKED:
                    return UserStartView.blocked(view)
                return UserStartView.registered(view)

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
            user = await access_policy.require_active_user(session, telegram_id)
            return required_user_view(user)

    async def require_superadmin(self, telegram_id: int) -> UserView:
        async with self.session_factory() as session:
            user = await access_policy.require_superadmin(session, telegram_id)
            return required_user_view(user)

    async def get_admin_panel_for_admin(
        self,
        admin_telegram_id: int,
    ) -> AdminPanelView:
        async with self.session_factory() as session:
            admin = await access_policy.require_admin(session, admin_telegram_id)
            return AdminPanelView(
                admin=required_user_view(admin),
                reviews=[],
            )


user_access_service = UserAccessService(SessionFactory)
