from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PlayerReward, Tournament, TournamentType
from app.db.models.enums import PlayerRewardType


@dataclass(frozen=True)
class PlayerRewardSourceRow:
    reward: PlayerReward
    tournament: Tournament
    tournament_type: TournamentType


class PlayerRewardRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_active_for_player(
        self,
        *,
        player_id: int,
        business_date: date,
    ) -> list[PlayerRewardSourceRow]:
        result = await self.session.execute(
            select(PlayerReward, Tournament, TournamentType)
            .join(Tournament, Tournament.id == PlayerReward.source_tournament_id)
            .join(TournamentType, TournamentType.id == Tournament.tournament_type_id)
            .where(
                PlayerReward.player_id == player_id,
                PlayerReward.reward_type == PlayerRewardType.PRIZE_STACK_BONUS,
                PlayerReward.redeemed_at.is_(None),
                PlayerReward.valid_through >= business_date,
            )
            .order_by(PlayerReward.valid_through, PlayerReward.issued_at, PlayerReward.id)
        )
        return [
            PlayerRewardSourceRow(
                reward=reward,
                tournament=tournament,
                tournament_type=tournament_type,
            )
            for reward, tournament, tournament_type in result.all()
        ]

    async def get_active_for_player(
        self,
        *,
        reward_id: int,
        player_id: int,
        business_date: date,
    ) -> PlayerReward | None:
        result = await self.session.execute(
            select(PlayerReward).where(
                PlayerReward.id == reward_id,
                PlayerReward.player_id == player_id,
                PlayerReward.reward_type == PlayerRewardType.PRIZE_STACK_BONUS,
                PlayerReward.redeemed_at.is_(None),
                PlayerReward.valid_through >= business_date,
            )
        )
        return result.scalar_one_or_none()

    async def get_for_redemption(
        self,
        *,
        reward_id: int,
        business_date: date,
    ) -> PlayerReward | None:
        result = await self.session.execute(
            select(PlayerReward).where(
                PlayerReward.id == reward_id,
                PlayerReward.reward_type == PlayerRewardType.PRIZE_STACK_BONUS,
                PlayerReward.redeemed_at.is_(None),
                PlayerReward.valid_through >= business_date,
            )
        )
        return result.scalar_one_or_none()

    async def get_source_row_by_id(self, reward_id: int) -> PlayerRewardSourceRow | None:
        result = await self.session.execute(
            select(PlayerReward, Tournament, TournamentType)
            .join(Tournament, Tournament.id == PlayerReward.source_tournament_id)
            .join(TournamentType, TournamentType.id == Tournament.tournament_type_id)
            .where(PlayerReward.id == reward_id)
        )
        row = result.one_or_none()
        if row is None:
            return None
        reward, tournament, tournament_type = row
        return PlayerRewardSourceRow(
            reward=reward,
            tournament=tournament,
            tournament_type=tournament_type,
        )

    async def exists_for_source(
        self,
        *,
        source_tournament_id: int,
        player_id: int,
        reward_type: PlayerRewardType,
    ) -> bool:
        result = await self.session.execute(
            select(PlayerReward.id).where(
                PlayerReward.source_tournament_id == source_tournament_id,
                PlayerReward.player_id == player_id,
                PlayerReward.reward_type == reward_type,
            )
        )
        return result.scalar_one_or_none() is not None

    async def has_redeemed_on_tournament_day(
        self,
        *,
        player_id: int,
        tournament_day: date,
    ) -> bool:
        result = await self.session.execute(
            select(func.count())
            .select_from(PlayerReward)
            .where(
                PlayerReward.player_id == player_id,
                PlayerReward.redeemed_tournament_day == tournament_day,
            )
        )
        return int(result.scalar_one()) > 0

    def add(self, reward: PlayerReward) -> None:
        self.session.add(reward)
