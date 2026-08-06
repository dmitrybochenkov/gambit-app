from aiogram import Router

from app.bot.telegram.handlers.admin import calendar, check_in, panel, results, schedule

router = Router(name="admin")
router.include_router(panel.router)
router.include_router(check_in.router)
router.include_router(results.router)
router.include_router(calendar.router)
router.include_router(schedule.router)

__all__ = ["router"]
