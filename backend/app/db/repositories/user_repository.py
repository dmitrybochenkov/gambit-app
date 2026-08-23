from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.db.models.enums import UserRole, UserStatus


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        result = await self.session.execute(select(User).where(User.telegram_id == telegram_id))
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: int) -> User | None:
        return await self.session.get(User, user_id)

    async def get_active_by_id(self, user_id: int) -> User | None:
        result = await self.session.execute(
            select(User).where(
                User.id == user_id,
                User.status == UserStatus.ACTIVE,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_display_name_normalized(self, display_name_normalized: str) -> list[User]:
        result = await self.session.execute(
            select(User).where(User.display_name_normalized == display_name_normalized)
        )
        return list(result.scalars())

    async def list_active_admins(self) -> list[User]:
        result = await self.session.execute(
            select(User)
            .where(
                User.status == UserStatus.ACTIVE,
                User.role.in_([UserRole.ADMIN, UserRole.SUPERADMIN]),
                User.telegram_id.is_not(None),
            )
            .order_by(User.id)
        )
        return list(result.scalars())

    async def list_active_superadmins_with_telegram(self) -> list[User]:
        result = await self.session.execute(
            select(User)
            .where(
                User.status == UserStatus.ACTIVE,
                User.role == UserRole.SUPERADMIN,
                User.telegram_id.is_not(None),
            )
            .order_by(User.id)
        )
        return list(result.scalars())

    async def list_active_users_for_play(self) -> list[User]:
        result = await self.session.execute(
            select(User)
            .where(User.status == UserStatus.ACTIVE)
            .order_by(User.display_name, User.id)
        )
        return list(result.scalars())

    async def count_active_telegram_users(self) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(User)
            .where(
                User.status == UserStatus.ACTIVE,
                User.telegram_id.is_not(None),
                User.telegram_id > 0,
            )
        )
        return int(result.scalar_one())

    async def list_admin_candidates(self) -> list[User]:
        result = await self.session.execute(
            select(User)
            .where(
                User.status == UserStatus.ACTIVE,
                User.role == UserRole.PLAYER,
                User.telegram_id.is_not(None),
            )
            .order_by(User.display_name, User.id)
        )
        return list(result.scalars())

    async def list_hall_of_fame_candidates(self) -> list[User]:
        result = await self.session.execute(select(User).order_by(User.display_name, User.id))
        return list(result.scalars())

    async def list_all_for_management(self) -> list[User]:
        result = await self.session.execute(select(User).order_by(User.display_name, User.id))
        return list(result.scalars())

    async def list_link_candidates(self) -> list[User]:
        result = await self.session.execute(
            select(User)
            .where(
                User.status == UserStatus.ACTIVE,
                User.telegram_id.is_(None),
            )
            .order_by(User.display_name, User.id)
        )
        return list(result.scalars())

    def add(self, user: User) -> None:
        self.session.add(user)

    def update_display_name(
        self,
        user: User,
        *,
        display_name: str,
        display_name_normalized: str,
    ) -> None:
        user.display_name = display_name
        user.display_name_normalized = display_name_normalized
