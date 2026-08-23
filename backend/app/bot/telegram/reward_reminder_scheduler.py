import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from datetime import timedelta

from aiogram import Bot

from app.bot.telegram.notifications import process_due_reward_expiration_reminders
from app.common.clock import Clock, club_clock
from app.config import settings
from app.domain.tournament_day import resolve_tournament_day

logger = logging.getLogger(__name__)

Sleep = Callable[[float], Awaitable[None]]
Process = Callable[[], Awaitable[None]]


class RewardReminderScheduler:
    def __init__(
        self,
        *,
        bot: Bot | None,
        clock: Clock = club_clock,
        run_hour: int = settings.reward_reminder_run_hour,
        sleep: Sleep = asyncio.sleep,
        process: Process | None = None,
    ) -> None:
        self.bot = bot
        self.clock = clock
        self.run_hour = run_hour
        self.sleep = sleep
        self.process = process or self._process_due_reminders
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self.bot is None or self._task is not None:
            return
        self._task = asyncio.create_task(self._run(), name="reward-reminder-scheduler")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _run(self) -> None:
        while True:
            try:
                await self.process()
            except Exception:
                logger.exception("Reward reminder processing failed")
            await self.sleep(self._seconds_until_next_run())

    async def _process_due_reminders(self) -> None:
        if self.bot is None:
            return
        await process_due_reward_expiration_reminders(
            self.bot,
            business_date=resolve_tournament_day(
                self.clock,
                settings.tournament_day_start_hour,
            ),
        )

    def _seconds_until_next_run(self) -> float:
        now = self.clock.now()
        next_run = now.replace(hour=self.run_hour, minute=0, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)
        return max((next_run - now).total_seconds(), 0.0)


reward_reminder_scheduler = RewardReminderScheduler(bot=None)


async def start_reward_reminder_scheduler(bot: Bot | None) -> None:
    reward_reminder_scheduler.bot = bot
    await reward_reminder_scheduler.start()


async def shutdown_reward_reminder_scheduler() -> None:
    await reward_reminder_scheduler.stop()
