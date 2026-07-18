from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Player, RegistrationMatch
from app.db.models.enums import PlayerRole, PlayerStatus, RegistrationMatchStatus


class PlayerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_telegram_id(self, telegram_id: int) -> Player | None:
        result = await self.session.execute(select(Player).where(Player.telegram_id == telegram_id))
        return result.scalar_one_or_none()

    async def get_by_id(self, player_id: int) -> Player | None:
        return await self.session.get(Player, player_id)

    async def list_pending(self, limit: int | None = None) -> list[Player]:
        query = (
            select(Player)
            .where(Player.status == PlayerStatus.PENDING)
            .order_by(Player.created_at)
        )
        if limit is not None:
            query = query.limit(limit)
        result = await self.session.execute(query)
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

    async def list_active_non_admins(self) -> list[Player]:
        result = await self.session.execute(
            select(Player)
            .where(
                Player.status == PlayerStatus.ACTIVE,
                Player.role == PlayerRole.USER,
                Player.telegram_id > 0,
            )
            .order_by(Player.id)
        )
        return list(result.scalars())

    async def full_name_exists(
        self,
        full_name: str,
        full_name_normalized: str,
        telegram_id: int,
    ) -> bool:
        result = await self.session.execute(
            select(Player.id).where(
                or_(
                    Player.full_name == full_name,
                    Player.full_name_normalized == full_name_normalized,
                ),
                Player.telegram_id != telegram_id,
                Player.telegram_id > 0,
                Player.status.in_(
                    [
                        PlayerStatus.PENDING,
                        PlayerStatus.ACTIVE,
                        PlayerStatus.BLOCKED,
                    ]
                ),
            )
        )
        return result.scalar_one_or_none() is not None

    async def nickname_exists(
        self,
        nickname: str,
        nickname_normalized: str,
        telegram_id: int,
    ) -> bool:
        result = await self.session.execute(
            select(Player.id).where(
                or_(
                    Player.nickname == nickname,
                    Player.nickname_normalized == nickname_normalized,
                ),
                Player.telegram_id != telegram_id,
                Player.telegram_id > 0,
                Player.status.in_(
                    [
                        PlayerStatus.PENDING,
                        PlayerStatus.ACTIVE,
                        PlayerStatus.BLOCKED,
                    ]
                ),
            )
        )
        return result.scalar_one_or_none() is not None

    async def list_historical_players(self) -> list[Player]:
        result = await self.session.execute(
            select(Player)
            .where(Player.telegram_id < 0)
            .order_by(Player.id)
        )
        return list(result.scalars())

    async def list_registration_matches(
        self,
        pending_player_id: int,
    ) -> list[tuple[RegistrationMatch, Player]]:
        result = await self.session.execute(
            select(RegistrationMatch, Player)
            .join(Player, Player.id == RegistrationMatch.historical_player_id)
            .where(
                RegistrationMatch.pending_player_id == pending_player_id,
                RegistrationMatch.status == RegistrationMatchStatus.CANDIDATE,
            )
            .order_by(RegistrationMatch.score.desc(), RegistrationMatch.id)
        )
        return list(result.all())

    async def save_pending_registration(
        self,
        telegram_id: int,
        full_name: str | None,
        full_name_normalized: str | None,
        nickname: str | None,
        nickname_normalized: str | None,
    ) -> Player:
        player = await self.get_by_telegram_id(telegram_id)
        if player is None:
            player = Player(
                telegram_id=telegram_id,
                full_name=full_name,
                full_name_normalized=full_name_normalized,
                nickname=nickname,
                nickname_normalized=nickname_normalized,
                status=PlayerStatus.PENDING,
            )
            self.session.add(player)
            return player

        player.full_name = full_name
        player.full_name_normalized = full_name_normalized
        player.nickname = nickname
        player.nickname_normalized = nickname_normalized
        player.status = PlayerStatus.PENDING
        player.approved_at = None
        player.approved_by_admin_id = None
        return player

    async def replace_registration_matches(
        self,
        pending_player_id: int,
        matches: list[tuple[int, int, str]],
    ) -> None:
        existing_matches = await self.session.execute(
            select(RegistrationMatch).where(
                RegistrationMatch.pending_player_id == pending_player_id
            )
        )
        for registration_match in existing_matches.scalars():
            await self.session.delete(registration_match)

        for historical_player_id, score, reason in matches:
            self.session.add(
                RegistrationMatch(
                    pending_player_id=pending_player_id,
                    historical_player_id=historical_player_id,
                    score=score,
                    reason=reason,
                    status=RegistrationMatchStatus.CANDIDATE,
                )
            )

    async def delete_registration_matches(self, pending_player_id: int) -> None:
        await self.session.execute(
            delete(RegistrationMatch).where(
                RegistrationMatch.pending_player_id == pending_player_id
            )
        )
