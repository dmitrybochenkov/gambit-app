from aiogram import Router

from app.bot.telegram.handlers.superadmin import (
    administrators,
    hall_of_fame,
    panel,
    registrations,
    seasons,
    tournament_close,
    tournaments,
    users,
)

router = Router(name="superadmin")
router.include_router(panel.router)
router.include_router(registrations.router)
router.include_router(administrators.router)
router.include_router(seasons.router)
router.include_router(tournaments.router)
router.include_router(tournament_close.router)
router.include_router(hall_of_fame.router)
router.include_router(users.router)

__all__ = ["router"]
