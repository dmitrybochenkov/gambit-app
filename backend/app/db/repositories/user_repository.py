from sqlalchemy import select
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

    async def list_active_players(self) -> list[User]:
        result = await self.session.execute(
            select(User)
            .where(
                User.status == UserStatus.ACTIVE,
                User.role == UserRole.PLAYER,
            )
            .order_by(User.display_name, User.id)
        )
        return list(result.scalars())

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

    async def list_link_candidates(self) -> list[User]:
        result = await self.session.execute(
            select(User)
            .where(
                User.status == UserStatus.ACTIVE,
                User.role == UserRole.PLAYER,
                User.telegram_id.is_(None),
            )
            .order_by(User.display_name, User.id)
        )
        return list(result.scalars())

    def add(self, user: User) -> None:
        self.session.add(user)
