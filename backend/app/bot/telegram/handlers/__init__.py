from aiogram import Router

from app.bot.telegram.handlers.admin import router as admin_router
from app.bot.telegram.handlers.user import router as user_router

router = Router()
router.include_router(admin_router)
router.include_router(user_router)
