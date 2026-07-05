from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Player
from app.db.models.enums import PlayerRole, PlayerStatus
from app.db.repositories.player_repository import PlayerRepository
from app.db.session import SessionFactory


class IdentityAlreadyExistsError(ValueError):
    def __init__(self, field: str) -> None:
        self.field = field
        super().__init__(f"{field} already exists")


class RegistrationNotAllowedError(ValueError):
    pass


class AdminAccessDeniedError(ValueError):
    pass


class PlayerNotFoundError(ValueError):
    pass


class RegistrationAlreadyReviewedError(ValueError):
    pass


class PlayerService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def get_by_telegram_id(self, telegram_id: int) -> Player | None:
        async with self.session_factory() as session:
            return await PlayerRepository(session).get_by_telegram_id(telegram_id)

    async def validate_unique_identity(
        self,
        telegram_id: int,
        full_name: str | None,
        nickname: str | None,
    ) -> None:
        async with self.session_factory() as session:
            repository = PlayerRepository(session)
            if full_name and await repository.full_name_exists(full_name, telegram_id):
                raise IdentityAlreadyExistsError("full_name")
            if nickname and await repository.nickname_exists(nickname, telegram_id):
                raise IdentityAlreadyExistsError("nickname")

    async def get_active_admins(self) -> list[Player]:
        async with self.session_factory() as session:
            return await PlayerRepository(session).list_active_admins()

    async def get_pending_for_admin(self, admin_telegram_id: int) -> list[Player]:
        async with self.session_factory() as session:
            repository = PlayerRepository(session)
            await self._require_admin(repository, admin_telegram_id)
            return await repository.list_pending()

    async def approve_registration(
        self,
        admin_telegram_id: int,
        player_id: int,
    ) -> Player:
        async with self.session_factory() as session:
            repository = PlayerRepository(session)
            admin = await self._require_admin(repository, admin_telegram_id)
            player = await self._require_pending_player(repository, player_id)

            player.status = PlayerStatus.ACTIVE
            player.approved_at = datetime.now(UTC)
            player.approved_by_admin_id = admin.id
            player.rejected_at = None
            player.rejected_by_admin_id = None
            player.rejection_reason = None
            await session.commit()
            await session.refresh(player)
            return player

    async def reject_registration(
        self,
        admin_telegram_id: int,
        player_id: int,
        reason: str = "Отклонено администратором",
    ) -> Player:
        async with self.session_factory() as session:
            repository = PlayerRepository(session)
            admin = await self._require_admin(repository, admin_telegram_id)
            player = await self._require_pending_player(repository, player_id)

            player.status = PlayerStatus.REJECTED
            player.approved_at = None
            player.approved_by_admin_id = None
            player.rejected_at = datetime.now(UTC)
            player.rejected_by_admin_id = admin.id
            player.rejection_reason = reason
            await session.commit()
            await session.refresh(player)
            return player

    async def submit_registration(
        self,
        telegram_id: int,
        full_name: str | None,
        nickname: str | None,
    ) -> Player:
        async with self.session_factory() as session:
            repository = PlayerRepository(session)
            current_player = await repository.get_by_telegram_id(telegram_id)
            if current_player and current_player.status in {
                PlayerStatus.ACTIVE,
                PlayerStatus.BLOCKED,
            }:
                raise RegistrationNotAllowedError

            if full_name and await repository.full_name_exists(full_name, telegram_id):
                raise IdentityAlreadyExistsError("full_name")
            if nickname and await repository.nickname_exists(nickname, telegram_id):
                raise IdentityAlreadyExistsError("nickname")

            player = await repository.save_pending_registration(
                telegram_id=telegram_id,
                full_name=full_name,
                nickname=nickname,
            )
            await session.commit()
            await session.refresh(player)
            return player

    @staticmethod
    async def _require_admin(
        repository: PlayerRepository,
        telegram_id: int,
    ) -> Player:
        admin = await repository.get_by_telegram_id(telegram_id)
        if (
            admin is None
            or admin.status != PlayerStatus.ACTIVE
            or admin.role not in {PlayerRole.ADMIN, PlayerRole.SUPERADMIN}
        ):
            raise AdminAccessDeniedError
        return admin

    @staticmethod
    async def _require_pending_player(
        repository: PlayerRepository,
        player_id: int,
    ) -> Player:
        player = await repository.get_by_id(player_id)
        if player is None:
            raise PlayerNotFoundError
        if player.status != PlayerStatus.PENDING:
            raise RegistrationAlreadyReviewedError
        return player


player_service = PlayerService(SessionFactory)
