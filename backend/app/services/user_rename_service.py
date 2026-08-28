from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models.enums import UserGender
from app.db.repositories.user_repository import UserRepository
from app.db.session import SessionFactory
from app.services.access_policy import access_policy
from app.services.dto.users import UserView
from app.services.player_search import rank_player_candidates
from app.services.user_common import (
    UserNotFoundError,
    require_valid_display_name,
    required_user_view,
)


class UserRenameNameOccupiedError(ValueError):
    pass


class UserRenameSameNameError(ValueError):
    pass


class UserRenameService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def require_rename_access(self, superadmin_telegram_id: int) -> None:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, superadmin_telegram_id)

    async def search_users_for_rename(
        self,
        superadmin_telegram_id: int,
        query: str,
    ) -> list[UserView]:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, superadmin_telegram_id)
            repository = UserRepository(session)
            candidates = rank_player_candidates(
                await repository.list_all_for_management(),
                query,
                limit=6,
            )
            return [required_user_view(candidate.user) for candidate in candidates]

    async def get_target_for_rename(
        self,
        superadmin_telegram_id: int,
        user_id: int,
    ) -> UserView:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, superadmin_telegram_id)
            user = await UserRepository(session).get_by_id(user_id)
            if user is None:
                raise UserNotFoundError
            return required_user_view(user)

    async def set_user_gender(
        self,
        actor_telegram_id: int,
        target_user_id: int,
        gender: UserGender | None,
    ) -> UserView:
        async with self.session_factory() as session:
            await access_policy.require_admin(session, actor_telegram_id)
            repository = UserRepository(session)
            target = await repository.get_by_id(target_user_id)
            if target is None:
                raise UserNotFoundError
            repository.update_gender(target, gender)
            await session.commit()
            await session.refresh(target)
            return required_user_view(target)

    async def set_user_gender_by_superadmin(
        self,
        superadmin_telegram_id: int,
        target_user_id: int,
        gender: UserGender | None,
    ) -> UserView:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, superadmin_telegram_id)
            repository = UserRepository(session)
            target = await repository.get_by_id(target_user_id)
            if target is None:
                raise UserNotFoundError
            repository.update_gender(target, gender)
            await session.commit()
            await session.refresh(target)
            return required_user_view(target)

    async def validate_new_display_name(
        self,
        superadmin_telegram_id: int,
        target_user_id: int,
        display_name: str,
    ) -> str:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, superadmin_telegram_id)
            repository = UserRepository(session)
            target = await repository.get_by_id(target_user_id)
            if target is None:
                raise UserNotFoundError
            normalized = _valid_normalized_name(_clean_display_name(display_name))
            if target.display_name_normalized == normalized:
                raise UserRenameSameNameError
            await self._ensure_name_available(repository, normalized, target_user_id)
            return normalized

    async def rename_user(
        self,
        superadmin_telegram_id: int,
        target_user_id: int,
        display_name: str,
        expected_old_display_name: str,
    ) -> UserView:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, superadmin_telegram_id)
            repository = UserRepository(session)
            target = await repository.get_by_id(target_user_id)
            if target is None or target.display_name != expected_old_display_name:
                raise UserNotFoundError
            clean_display_name = _clean_display_name(display_name)
            normalized = _valid_normalized_name(clean_display_name)
            if target.display_name_normalized == normalized:
                raise UserRenameSameNameError
            await self._ensure_name_available(repository, normalized, target_user_id)
            repository.update_display_name(
                target,
                display_name=clean_display_name,
                display_name_normalized=normalized,
            )
            await session.commit()
            await session.refresh(target)
            return required_user_view(target)

    async def _ensure_name_available(
        self,
        repository: UserRepository,
        normalized: str,
        target_user_id: int,
    ) -> None:
        existing_users = await repository.list_by_display_name_normalized(normalized)
        if any(user.id != target_user_id for user in existing_users):
            raise UserRenameNameOccupiedError


def _valid_normalized_name(display_name: str) -> str:
    return require_valid_display_name(display_name)


def _clean_display_name(display_name: str) -> str:
    return " ".join(display_name.split()).strip()


user_rename_service = UserRenameService(SessionFactory)
