from aiogram import Router

from app.bot.telegram.handlers.user import (
    hall_of_fame,
    history,
    profile,
    rating,
    registration,
    start,
    tournaments,
)

router = Router(name="user")
router.include_router(start.router)
router.include_router(registration.router)
router.include_router(tournaments.router)
router.include_router(rating.router)
router.include_router(history.router)
router.include_router(hall_of_fame.router)
router.include_router(profile.router)

__all__ = ["router"]
