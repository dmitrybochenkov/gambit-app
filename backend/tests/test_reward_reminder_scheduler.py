import asyncio
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app.bot.telegram.reward_reminder_scheduler import RewardReminderScheduler
from app.common.clock import FixedClock


async def test_reward_reminder_scheduler_startup_catchup_and_shutdown() -> None:
    calls = 0
    sleeping = asyncio.Event()

    async def process() -> None:
        nonlocal calls
        calls += 1

    async def sleep(_seconds: float) -> None:
        sleeping.set()
        await asyncio.Future()

    scheduler = RewardReminderScheduler(
        bot=SimpleNamespace(),
        clock=FixedClock(datetime(2026, 8, 29, 10, tzinfo=ZoneInfo("Europe/Moscow"))),
        sleep=sleep,
        process=process,
    )

    await scheduler.start()
    await asyncio.wait_for(sleeping.wait(), timeout=1)
    await scheduler.stop()

    assert calls == 1


async def test_reward_reminder_scheduler_daily_loop_invokes_processing_again() -> None:
    calls = 0
    second_call = asyncio.Event()

    async def process() -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            second_call.set()

    async def sleep(_seconds: float) -> None:
        await asyncio.sleep(0)

    scheduler = RewardReminderScheduler(
        bot=SimpleNamespace(),
        clock=FixedClock(datetime(2026, 8, 29, 10, tzinfo=ZoneInfo("Europe/Moscow"))),
        sleep=sleep,
        process=process,
    )

    await scheduler.start()
    await asyncio.wait_for(second_call.wait(), timeout=1)
    await scheduler.stop()

    assert calls >= 2


async def test_reward_reminder_scheduler_process_exception_does_not_stop_loop() -> None:
    calls = 0
    recovered = asyncio.Event()

    async def process() -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("temporary")
        recovered.set()

    async def sleep(_seconds: float) -> None:
        await asyncio.sleep(0)

    scheduler = RewardReminderScheduler(
        bot=SimpleNamespace(),
        clock=FixedClock(datetime(2026, 8, 29, 10, tzinfo=ZoneInfo("Europe/Moscow"))),
        sleep=sleep,
        process=process,
    )

    await scheduler.start()
    await asyncio.wait_for(recovered.wait(), timeout=1)
    await scheduler.stop()

    assert calls >= 2
