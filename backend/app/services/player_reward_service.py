from datetime import date, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.clock import Clock, club_clock
from app.config import settings
from app.db.models import PlayerReward, Tournament
from app.db.models.enums import PlayerRewardType, TournamentStatus
from app.db.repositories.player_reward_repository import (
    PlayerRewardRepository,
    PlayerRewardSourceRow,
)
from app.db.repositories.tournament_repository import TournamentRepository
from app.db.repositories.tournament_result_repository import TournamentResultRepository
from app.db.repositories.user_repository import UserRepository
from app.db.session import SessionFactory
from app.domain.tournament_day import resolve_tournament_day
from app.services.access_policy import access_policy
from app.services.dto.rewards import PlayerRewardView

PRIZE_STACK_BONUS_BY_PLACE = {
    1: 40_000,
    2: 30_000,
    3: 20_000,
}
REWARD_VALID_DAYS = 7


class PlayerRewardNotFoundError(ValueError):
    pass


class PlayerRewardAlreadyRedeemedTodayError(ValueError):
    pass


class PlayerRewardUserNotFoundError(ValueError):
    pass


class PlayerRewardService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Clock = club_clock,
        tournament_day_start_hour: int = settings.tournament_day_start_hour,
    ) -> None:
        self.session_factory = session_factory
        self.clock = clock
        self.tournament_day_start_hour = tournament_day_start_hour

    async def list_active_rewards_for_player(
        self,
        *,
        player_id: int,
        business_date: date,
    ) -> tuple[PlayerRewardView, ...]:
        async with self.session_factory() as session:
            return await self._list_active_reward_views(session, player_id, business_date)

    async def list_active_rewards_for_check_in(
        self,
        *,
        admin_telegram_id: int,
        tournament_id: int,
        player_id: int,
    ) -> tuple[PlayerRewardView, ...]:
        business_date = self._tournament_day()
        async with self.session_factory() as session:
            await access_policy.require_admin(session, admin_telegram_id)
            tournament = await TournamentRepository(session).get_by_id(tournament_id)
            if (
                tournament is None
                or tournament.date != business_date
                or tournament.status != TournamentStatus.ACTIVE
            ):
                raise PlayerRewardNotFoundError
            return await self._list_active_reward_views(session, player_id, business_date)

    async def get_active_reward_for_player(
        self,
        *,
        admin_telegram_id: int,
        player_id: int,
        reward_id: int,
    ) -> PlayerRewardView:
        business_date = self._tournament_day()
        async with self.session_factory() as session:
            await access_policy.require_admin(session, admin_telegram_id)
            reward = await PlayerRewardRepository(session).get_active_for_player(
                reward_id=reward_id,
                player_id=player_id,
                business_date=business_date,
            )
            if reward is None:
                raise PlayerRewardNotFoundError
            rows = await PlayerRewardRepository(session).list_active_for_player(
                player_id=player_id,
                business_date=business_date,
            )
            return next(_reward_view(row) for row in rows if row.reward.id == reward.id)

    async def redeem_reward(
        self,
        *,
        admin_telegram_id: int,
        tournament_id: int,
        reward_id: int,
    ) -> PlayerRewardView:
        business_date = self._tournament_day()
        async with self.session_factory() as session:
            admin = await access_policy.require_admin(session, admin_telegram_id)
            reward_repository = PlayerRewardRepository(session)
            reward = await reward_repository.get_for_redemption(
                reward_id=reward_id,
                business_date=business_date,
            )
            if reward is None:
                raise PlayerRewardNotFoundError
            if await reward_repository.has_redeemed_on_tournament_day(
                player_id=reward.player_id,
                tournament_day=business_date,
            ):
                raise PlayerRewardAlreadyRedeemedTodayError
            tournament = await TournamentRepository(session).get_by_id(tournament_id)
            if (
                tournament is None
                or tournament.date != business_date
                or tournament.status != TournamentStatus.ACTIVE
            ):
                raise PlayerRewardNotFoundError

            reward.redeemed_at = self.clock.now()
            reward.redeemed_tournament_id = tournament.id
            reward.redeemed_by_user_id = admin.id
            reward.redeemed_tournament_day = business_date
            try:
                await session.flush()
            except IntegrityError as exc:
                await session.rollback()
                raise PlayerRewardAlreadyRedeemedTodayError from exc

            view = await self._reward_view_by_id(session, reward.id)
            await session.commit()
            return view

    async def issue_prize_stack_bonuses_for_closed_tournament(
        self,
        session: AsyncSession,
        tournament: Tournament,
        *,
        issued_date: date,
    ) -> None:
        repository = PlayerRewardRepository(session)
        results = await TournamentResultRepository(session).list_by_tournament(tournament.id)
        issued_at = self.clock.now()
        valid_through = issued_date + timedelta(days=REWARD_VALID_DAYS)
        for result in results:
            chips_amount = PRIZE_STACK_BONUS_BY_PLACE.get(result.place)
            if chips_amount is None:
                continue
            if await repository.exists_for_source(
                source_tournament_id=tournament.id,
                player_id=result.player_id,
                reward_type=PlayerRewardType.PRIZE_STACK_BONUS,
            ):
                continue
            repository.add(
                PlayerReward(
                    player_id=result.player_id,
                    reward_type=PlayerRewardType.PRIZE_STACK_BONUS,
                    chips_amount=chips_amount,
                    source_tournament_id=tournament.id,
                    source_place=result.place,
                    issued_at=issued_at,
                    valid_through=valid_through,
                )
            )

    async def _list_active_reward_views(
        self,
        session: AsyncSession,
        player_id: int,
        business_date: date,
    ) -> tuple[PlayerRewardView, ...]:
        user = await UserRepository(session).get_active_by_id(player_id)
        if user is None:
            raise PlayerRewardUserNotFoundError
        rows = await PlayerRewardRepository(session).list_active_for_player(
            player_id=player_id,
            business_date=business_date,
        )
        return tuple(_reward_view(row) for row in rows)

    async def _reward_view_by_id(
        self,
        session: AsyncSession,
        reward_id: int,
    ) -> PlayerRewardView:
        row = await PlayerRewardRepository(session).get_source_row_by_id(reward_id)
        if row is None:
            raise PlayerRewardNotFoundError
        return _reward_view(row)

    def _tournament_day(self) -> date:
        return resolve_tournament_day(self.clock, self.tournament_day_start_hour)


def _reward_view(row: PlayerRewardSourceRow) -> PlayerRewardView:
    return PlayerRewardView(
        reward_id=row.reward.id,
        player_id=row.reward.player_id,
        chips_amount=row.reward.chips_amount,
        source_place=row.reward.source_place,
        source_tournament_id=row.reward.source_tournament_id,
        source_tournament_date=row.tournament.date,
        source_tournament_name=row.tournament_type.name,
        valid_through=row.reward.valid_through,
    )


player_reward_service = PlayerRewardService(SessionFactory)
