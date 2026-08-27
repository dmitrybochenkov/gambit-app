from datetime import date, datetime, time, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.clock import Clock, club_clock
from app.config import settings
from app.db.models import PlayerReward, Tournament
from app.db.models.enums import PlayerRewardType
from app.db.repositories.player_reward_repository import (
    PlayerRewardReminderRow,
    PlayerRewardRepository,
    PlayerRewardSourceRow,
)
from app.db.repositories.tournament_repository import TournamentRepository
from app.db.repositories.tournament_result_repository import TournamentResultRepository
from app.db.repositories.tournament_type_repository import TournamentTypeRepository
from app.db.repositories.user_repository import UserRepository
from app.db.session import SessionFactory
from app.domain.open_tournament_edit_policy import can_edit_open_tournament_for_actor
from app.domain.tournament_day import resolve_tournament_day
from app.services.access_policy import access_policy
from app.services.dto.rewards import (
    PlayerRewardCorrectionChangeView,
    PlayerRewardCorrectionNotificationView,
    PlayerRewardCorrectionResultView,
    PlayerRewardExpirationReminderGroupView,
    PlayerRewardExpirationReminderItemView,
    PlayerRewardNotificationView,
    PlayerRewardView,
    PrizeStackBonusSourceResultView,
)

PRIZE_STACK_BONUS_BY_PLACE = {
    1: 40_000,
    2: 30_000,
    3: 20_000,
}
REWARD_VALID_DAYS = 7
EXPIRATION_REMINDER_DAYS_BEFORE = 4


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

    async def list_due_expiration_reminder_groups(
        self,
        *,
        business_date: date,
    ) -> tuple[PlayerRewardExpirationReminderGroupView, ...]:
        async with self.session_factory() as session:
            rows = await PlayerRewardRepository(session).list_due_expiration_reminder_candidates(
                business_date=business_date,
                due_until=business_date + timedelta(days=EXPIRATION_REMINDER_DAYS_BEFORE),
            )
            return _reminder_groups(rows)

    async def get_due_expiration_reminder_group(
        self,
        *,
        player_id: int,
        reward_ids: tuple[int, ...],
        business_date: date,
    ) -> PlayerRewardExpirationReminderGroupView | None:
        async with self.session_factory() as session:
            rows = await PlayerRewardRepository(session).list_due_expiration_reminders_by_ids(
                player_id=player_id,
                reward_ids=reward_ids,
                business_date=business_date,
                due_until=business_date + timedelta(days=EXPIRATION_REMINDER_DAYS_BEFORE),
            )
            groups = _reminder_groups(rows)
            return groups[0] if groups else None

    async def mark_expiration_reminders_sent(
        self,
        *,
        reward_ids: tuple[int, ...],
        business_date: date,
    ) -> int:
        async with self.session_factory() as session:
            count = await PlayerRewardRepository(session).mark_expiration_reminders_sent(
                reward_ids=reward_ids,
                business_date=business_date,
                due_until=business_date + timedelta(days=EXPIRATION_REMINDER_DAYS_BEFORE),
                sent_at=self.clock.now(),
            )
            await session.commit()
            return count

    async def list_active_rewards_for_check_in(
        self,
        *,
        admin_telegram_id: int,
        tournament_id: int,
        player_id: int,
    ) -> tuple[PlayerRewardView, ...]:
        business_date = self._tournament_day()
        async with self.session_factory() as session:
            actor = await access_policy.require_admin(session, admin_telegram_id)
            tournament = await TournamentRepository(session).get_by_id(tournament_id)
            if tournament is None or not can_edit_open_tournament_for_actor(
                actor_role=actor.role,
                tournament_status=tournament.status,
                tournament_date=tournament.date,
                business_date=business_date,
                admin_current_day_only=True,
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
            tournament = await TournamentRepository(session).get_by_id(tournament_id)
            if tournament is None or not can_edit_open_tournament_for_actor(
                actor_role=admin.role,
                tournament_status=tournament.status,
                tournament_date=tournament.date,
                business_date=business_date,
                admin_current_day_only=True,
            ):
                raise PlayerRewardNotFoundError
            try:
                view = await self.redeem_reward_in_session(
                    session,
                    admin_user_id=admin.id,
                    tournament_id=tournament.id,
                    reward_id=reward_id,
                    player_id=None,
                    business_date=business_date,
                )
            except IntegrityError as exc:
                await session.rollback()
                raise PlayerRewardAlreadyRedeemedTodayError from exc
            await session.commit()
            return view

    async def redeem_reward_in_session(
        self,
        session: AsyncSession,
        *,
        admin_user_id: int,
        tournament_id: int,
        reward_id: int,
        player_id: int | None,
        business_date: date,
    ) -> PlayerRewardView:
        reward_repository = PlayerRewardRepository(session)
        reward = await reward_repository.get_for_redemption(
            reward_id=reward_id,
            business_date=business_date,
        )
        if reward is None or (player_id is not None and reward.player_id != player_id):
            raise PlayerRewardNotFoundError
        if await reward_repository.has_redeemed_on_tournament_day(
            player_id=reward.player_id,
            tournament_day=business_date,
        ):
            raise PlayerRewardAlreadyRedeemedTodayError

        reward.redeemed_at = self.clock.now()
        reward.redeemed_tournament_id = tournament_id
        reward.redeemed_by_user_id = admin_user_id
        reward.redeemed_tournament_day = business_date
        await session.flush()
        return await self._reward_view_by_id(session, reward.id)

    async def issue_prize_stack_bonuses_for_closed_tournament(
        self,
        session: AsyncSession,
        tournament: Tournament,
        *,
        issued_date: date,
    ) -> tuple[PlayerRewardNotificationView, ...]:
        repository = PlayerRewardRepository(session)
        tournament_type = await TournamentTypeRepository(session).get_by_id(
            tournament.tournament_type_id
        )
        if tournament_type is None:
            return ()
        results = await TournamentResultRepository(session).list_by_tournament(tournament.id)
        issued_at = self.clock.now()
        valid_through = self._prize_stack_bonus_valid_through(issued_date)
        issued_rewards: list[tuple[PlayerReward, int]] = []
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
            reward = PlayerReward(
                player_id=result.player_id,
                reward_type=PlayerRewardType.PRIZE_STACK_BONUS,
                chips_amount=chips_amount,
                source_tournament_id=tournament.id,
                source_place=result.place,
                issued_at=issued_at,
                valid_through=valid_through,
            )
            repository.add(reward)
            issued_rewards.append((reward, result.player_id))
        if not issued_rewards:
            return ()

        await session.flush()
        views = []
        for reward, player_id in issued_rewards:
            user = await UserRepository(session).get_by_id(player_id)
            views.append(
                PlayerRewardNotificationView(
                    reward_id=reward.id,
                    player_id=player_id,
                    telegram_id=user.telegram_id if user is not None else None,
                    chips_amount=reward.chips_amount,
                    source_place=reward.source_place,
                    source_tournament_id=tournament.id,
                    source_tournament_date=tournament.date,
                    source_tournament_name=tournament_type.name,
                    valid_through=reward.valid_through,
                )
            )
        return tuple(views)

    async def reconcile_prize_stack_bonuses_for_closed_tournament(
        self,
        session: AsyncSession,
        tournament: Tournament,
        *,
        source_results: tuple[PrizeStackBonusSourceResultView, ...],
    ) -> PlayerRewardCorrectionResultView:
        return await self._plan_prize_stack_bonus_reconciliation_for_closed_tournament(
            session,
            tournament,
            source_results=source_results,
            apply=True,
        )

    async def preview_prize_stack_bonus_reconciliation_for_closed_tournament(
        self,
        session: AsyncSession,
        tournament: Tournament,
        *,
        source_results: tuple[PrizeStackBonusSourceResultView, ...],
    ) -> PlayerRewardCorrectionResultView:
        return await self._plan_prize_stack_bonus_reconciliation_for_closed_tournament(
            session,
            tournament,
            source_results=source_results,
            apply=False,
        )

    async def _plan_prize_stack_bonus_reconciliation_for_closed_tournament(
        self,
        session: AsyncSession,
        tournament: Tournament,
        *,
        source_results: tuple[PrizeStackBonusSourceResultView, ...],
        apply: bool,
    ) -> PlayerRewardCorrectionResultView:
        reward_repository = PlayerRewardRepository(session)
        tournament_type = await TournamentTypeRepository(session).get_by_id(
            tournament.tournament_type_id
        )
        if tournament_type is None:
            return PlayerRewardCorrectionResultView(
                reward_changes=(),
                used_reward_warnings=(),
                player_notifications=(),
            )

        desired = {
            result.player_id: result
            for result in source_results
            if result.place in PRIZE_STACK_BONUS_BY_PLACE
        }
        existing_rows = await reward_repository.list_for_source(
            source_tournament_id=tournament.id,
            reward_type=PlayerRewardType.PRIZE_STACK_BONUS,
        )
        existing_by_player = {row.reward.player_id: row for row in existing_rows}
        issued_at, valid_through = self._source_reward_lifecycle(tournament, existing_rows)
        changes: list[PlayerRewardCorrectionChangeView] = []
        warnings: list[PlayerRewardCorrectionChangeView] = []
        notifications: list[PlayerRewardCorrectionNotificationView] = []

        for player_id, row in existing_by_player.items():
            reward = row.reward
            wanted = desired.get(player_id)
            user = await UserRepository(session).get_by_id(player_id)
            display_name = user.display_name if user is not None else str(player_id)
            telegram_id = user.telegram_id if user is not None else None
            if wanted is None:
                change = PlayerRewardCorrectionChangeView(
                    player_id=player_id,
                    display_name=display_name,
                    old_chips_amount=reward.chips_amount,
                    new_chips_amount=None,
                    used=reward.redeemed_at is not None,
                )
                changes.append(change)
                if change.used:
                    warnings.append(change)
                notifications.append(
                    self._reward_correction_notification(
                        tournament=tournament,
                        tournament_name=tournament_type.name,
                        player_id=player_id,
                        telegram_id=telegram_id,
                        valid_through=reward.valid_through,
                        old_chips_amount=reward.chips_amount,
                        new_chips_amount=None,
                    )
                )
                if apply:
                    await reward_repository.delete(reward)
                continue

            if wanted.place is None:
                continue
            chips_amount = PRIZE_STACK_BONUS_BY_PLACE[wanted.place]
            if reward.chips_amount == chips_amount and reward.source_place == wanted.place:
                continue
            change = PlayerRewardCorrectionChangeView(
                player_id=player_id,
                display_name=display_name,
                old_chips_amount=reward.chips_amount,
                new_chips_amount=chips_amount,
                used=reward.redeemed_at is not None,
            )
            changes.append(change)
            if change.used:
                warnings.append(change)
            notifications.append(
                self._reward_correction_notification(
                    tournament=tournament,
                    tournament_name=tournament_type.name,
                    player_id=player_id,
                    telegram_id=telegram_id,
                    valid_through=reward.valid_through,
                    old_chips_amount=reward.chips_amount,
                    new_chips_amount=chips_amount,
                )
            )
            if apply:
                reward.chips_amount = chips_amount
                reward.source_place = wanted.place
                reward.valid_through = valid_through

        for player_id, result in desired.items():
            if player_id in existing_by_player:
                continue
            if result.place is None:
                continue
            chips_amount = PRIZE_STACK_BONUS_BY_PLACE[result.place]
            if apply:
                reward = PlayerReward(
                    player_id=player_id,
                    reward_type=PlayerRewardType.PRIZE_STACK_BONUS,
                    chips_amount=chips_amount,
                    source_tournament_id=tournament.id,
                    source_place=result.place,
                    issued_at=issued_at,
                    valid_through=valid_through,
                )
                reward_repository.add(reward)
            changes.append(
                PlayerRewardCorrectionChangeView(
                    player_id=player_id,
                    display_name=result.display_name,
                    old_chips_amount=None,
                    new_chips_amount=chips_amount,
                )
            )
            notifications.append(
                self._reward_correction_notification(
                    tournament=tournament,
                    tournament_name=tournament_type.name,
                    player_id=player_id,
                    telegram_id=result.telegram_id,
                    valid_through=valid_through,
                    old_chips_amount=None,
                    new_chips_amount=chips_amount,
                )
            )

        if apply and changes:
            await session.flush()
        return PlayerRewardCorrectionResultView(
            reward_changes=tuple(changes),
            used_reward_warnings=tuple(warnings),
            player_notifications=tuple(notifications),
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

    @staticmethod
    def _prize_stack_bonus_valid_through(issued_date: date) -> date:
        return issued_date + timedelta(days=REWARD_VALID_DAYS)

    def _source_reward_lifecycle(
        self,
        tournament: Tournament,
        existing_rows: list[PlayerRewardSourceRow],
    ) -> tuple[datetime, date]:
        if existing_rows:
            return (
                min(row.reward.issued_at for row in existing_rows),
                min(row.reward.valid_through for row in existing_rows),
            )
        return (
            self._source_reward_issued_at(tournament.date),
            self._prize_stack_bonus_valid_through(tournament.date),
        )

    def _source_reward_issued_at(self, issued_date: date) -> datetime:
        now = self.clock.now()
        return datetime.combine(issued_date, time.min, tzinfo=now.tzinfo)

    @staticmethod
    def _reward_correction_notification(
        *,
        tournament: Tournament,
        tournament_name: str,
        player_id: int,
        telegram_id: int | None,
        valid_through: date,
        old_chips_amount: int | None,
        new_chips_amount: int | None,
    ) -> PlayerRewardCorrectionNotificationView:
        return PlayerRewardCorrectionNotificationView(
            player_id=player_id,
            telegram_id=telegram_id,
            source_tournament_id=tournament.id,
            source_tournament_date=tournament.date,
            source_tournament_name=tournament_name,
            valid_through=valid_through,
            old_chips_amount=old_chips_amount,
            new_chips_amount=new_chips_amount,
        )


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


def _reminder_groups(
    rows: list[PlayerRewardReminderRow],
) -> tuple[PlayerRewardExpirationReminderGroupView, ...]:
    grouped: dict[tuple[int, int], list[PlayerRewardExpirationReminderItemView]] = {}
    for row in rows:
        key = (row.reward.player_id, row.telegram_id)
        grouped.setdefault(key, []).append(
            PlayerRewardExpirationReminderItemView(
                reward_id=row.reward.id,
                chips_amount=row.reward.chips_amount,
                valid_through=row.reward.valid_through,
            )
        )
    return tuple(
        PlayerRewardExpirationReminderGroupView(
            player_id=player_id,
            telegram_id=telegram_id,
            rewards=tuple(rewards),
        )
        for (player_id, telegram_id), rewards in grouped.items()
    )


player_reward_service = PlayerRewardService(SessionFactory)
