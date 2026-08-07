from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models.enums import UserRole, UserStatus
from app.db.repositories.user_repository import UserRepository
from app.db.session import SessionFactory
from app.services.access_policy import access_policy
from app.services.dto.users import UserView
from app.services.user_common import (
    UserNotFoundError,
    UserRoleAlreadyAssignedError,
    required_user_view,
)


class AdminManagementService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def list_admin_candidates_for_superadmin(
        self,
        superadmin_telegram_id: int,
    ) -> list[UserView]:
        async with self.session_factory() as session:
            repository = UserRepository(session)
            await access_policy.require_superadmin(session, superadmin_telegram_id)
            users = await repository.list_admin_candidates()
            return [required_user_view(user) for user in users]

    async def add_admin(
        self,
        superadmin_telegram_id: int,
        user_id: int,
    ) -> UserView:
        async with self.session_factory() as session:
            repository = UserRepository(session)
            await access_policy.require_superadmin(session, superadmin_telegram_id)
            user = await repository.get_by_id(user_id)
            if user is None or user.status != UserStatus.ACTIVE:
                raise UserNotFoundError
            if user.role != UserRole.PLAYER:
                raise UserRoleAlreadyAssignedError

            user.role = UserRole.ADMIN
            await session.commit()
            await session.refresh(user)
            return required_user_view(user)


admin_management_service = AdminManagementService(SessionFactory)
