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
        actor_user_id: int,
    ) -> User:
        user = await UserRepository(session).get_by_id(actor_user_id)
        return self._require_active(user)

    async def require_admin(
        self,
        session: AsyncSession,
        actor_user_id: int,
    ) -> User:
        user = await self.require_active_user(session, actor_user_id)
        return self._require_role(user, {UserRole.ADMIN, UserRole.SUPERADMIN})

    async def require_superadmin(
        self,
        session: AsyncSession,
        actor_user_id: int,
    ) -> User:
        user = await self.require_active_user(session, actor_user_id)
        return self._require_role(user, {UserRole.SUPERADMIN})

    async def require_active_user_by_telegram_id(
        self,
        session: AsyncSession,
        telegram_id: int,
    ) -> User:
        user = await UserRepository(session).get_by_telegram_id(telegram_id)
        return self._require_active(user)

    async def require_admin_by_telegram_id(
        self,
        session: AsyncSession,
        telegram_id: int,
    ) -> User:
        user = await self.require_active_user_by_telegram_id(session, telegram_id)
        return self._require_role(user, {UserRole.ADMIN, UserRole.SUPERADMIN})

    async def require_superadmin_by_telegram_id(
        self,
        session: AsyncSession,
        telegram_id: int,
    ) -> User:
        user = await self.require_active_user_by_telegram_id(session, telegram_id)
        return self._require_role(user, {UserRole.SUPERADMIN})

    @staticmethod
    def _require_active(user: User | None) -> User:
        if user is None or user.status != UserStatus.ACTIVE:
            raise ActiveUserRequiredError
        return user

    @staticmethod
    def _require_role(user: User, allowed_roles: set[UserRole]) -> User:
        if user.role not in allowed_roles:
            raise AdminAccessDeniedError
        return user


access_policy = AccessPolicy()
