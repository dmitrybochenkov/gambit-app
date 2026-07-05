from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Player
from app.db.models.enums import PlayerRole, PlayerStatus


class PlayerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_telegram_id(self, telegram_id: int) -> Player | None:
        result = await self.session.execute(select(Player).where(Player.telegram_id == telegram_id))
        return result.scalar_one_or_none()

    async def get_by_id(self, player_id: int) -> Player | None:
        return await self.session.get(Player, player_id)

    async def list_pending(self, limit: int = 20) -> list[Player]:
        result = await self.session.execute(
            select(Player)
            .where(Player.status == PlayerStatus.PENDING)
            .order_by(Player.created_at)
            .limit(limit)
        )
        return list(result.scalars())

    async def list_active_admins(self) -> list[Player]:
        result = await self.session.execute(
            select(Player)
            .where(
                Player.status == PlayerStatus.ACTIVE,
                Player.role.in_([PlayerRole.ADMIN, PlayerRole.SUPERADMIN]),
            )
            .order_by(Player.id)
        )
        return list(result.scalars())

    async def full_name_exists(self, full_name: str, telegram_id: int) -> bool:
        result = await self.session.execute(
            select(Player.id).where(
                Player.full_name == full_name,
                Player.telegram_id != telegram_id,
            )
        )
        return result.scalar_one_or_none() is not None

    async def nickname_exists(self, nickname: str, telegram_id: int) -> bool:
        result = await self.session.execute(
            select(Player.id).where(
                Player.nickname == nickname,
                Player.telegram_id != telegram_id,
            )
        )
        return result.scalar_one_or_none() is not None

    async def save_pending_registration(
        self,
        telegram_id: int,
        full_name: str | None,
        nickname: str | None,
    ) -> Player:
        player = await self.get_by_telegram_id(telegram_id)
        if player is None:
            player = Player(
                telegram_id=telegram_id,
                full_name=full_name,
                nickname=nickname,
                status=PlayerStatus.PENDING,
            )
            self.session.add(player)
            return player

        player.full_name = full_name
        player.nickname = nickname
        player.status = PlayerStatus.PENDING
        player.approved_at = None
        player.approved_by_admin_id = None
        player.rejected_at = None
        player.rejected_by_admin_id = None
        player.rejection_reason = None
        return player
