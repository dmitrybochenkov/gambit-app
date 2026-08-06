from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.db.models.enums import UserRole, UserStatus
from app.db.repositories.user_repository import UserRepository


class ActiveUserRequiredError(ValueError):
    pass


class AdminAccessDeniedError(ValueError):
    pass


class AccessPolicy:
    async def require_active_user(
        self,
        session: AsyncSession,
        telegram_id: int,
    ) -> User:
        user = await UserRepository(session).get_by_telegram_id(telegram_id)
        if user is None or user.status != UserStatus.ACTIVE:
            raise ActiveUserRequiredError
        return user

    async def require_admin(
        self,
        session: AsyncSession,
        telegram_id: int,
    ) -> User:
        user = await self.require_active_user(session, telegram_id)
        if user.role not in {UserRole.ADMIN, UserRole.SUPERADMIN}:
            raise AdminAccessDeniedError
        return user

    async def require_superadmin(
        self,
        session: AsyncSession,
        telegram_id: int,
    ) -> User:
        user = await self.require_active_user(session, telegram_id)
        if user.role != UserRole.SUPERADMIN:
            raise AdminAccessDeniedError
        return user


access_policy = AccessPolicy()
