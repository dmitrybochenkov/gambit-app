from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Player
from app.db.models.enums import PlayerStatus
from app.db.repositories.player_repository import PlayerRepository
from app.db.session import SessionFactory


class IdentityAlreadyExistsError(ValueError):
    def __init__(self, field: str) -> None:
        self.field = field
        super().__init__(f"{field} already exists")


class RegistrationNotAllowedError(ValueError):
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


player_service = PlayerService(SessionFactory)
