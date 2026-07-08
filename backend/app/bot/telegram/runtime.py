import asyncio

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from app.bot.telegram.handlers import router
from app.bot.telegram.notifications import notify_admins_about_calendar_prompt
from app.config import settings
from app.services.calendar_service import calendar_service

telegram_dispatcher = Dispatcher(storage=MemoryStorage())
telegram_dispatcher.include_router(router)

telegram_bot = Bot(token=settings.telegram_bot_token) if settings.telegram_bot_token else None
calendar_checks_task: asyncio.Task[None] | None = None


async def setup_telegram_webhook() -> None:
    global calendar_checks_task
    public_base_url = settings.effective_public_base_url
    if telegram_bot is None or not public_base_url:
        return

    await telegram_bot.set_webhook(
        url=f"{public_base_url}/webhooks/tg",
        secret_token=settings.telegram_webhook_secret or None,
        drop_pending_updates=True,
        allowed_updates=telegram_dispatcher.resolve_used_update_types(),
    )
    if settings.admin_calendar_checks_enabled and calendar_checks_task is None:
        calendar_checks_task = asyncio.create_task(run_calendar_checks())


async def shutdown_telegram_bot() -> None:
    global calendar_checks_task
    if calendar_checks_task is not None:
        calendar_checks_task.cancel()
        try:
            await calendar_checks_task
        except asyncio.CancelledError:
            pass
        calendar_checks_task = None

    if telegram_bot is None:
        return

    await telegram_bot.session.close()


async def run_calendar_checks() -> None:
    while True:
        await send_due_calendar_prompts()
        await asyncio.sleep(settings.admin_calendar_check_interval_seconds)


async def send_due_calendar_prompts() -> None:
    if telegram_bot is None:
        return

    prompts = await calendar_service.collect_due_prompts()
    for prompt in prompts:
        await notify_admins_about_calendar_prompt(telegram_bot, prompt)
        await calendar_service.mark_prompt_notified(prompt.id)
