from app.bot.telegram.texts.admin.results import (
    ADMIN_RESULTS_CANCELLED,
    ADMIN_RESULTS_NOT_FOUND,
)
from app.bot.telegram.texts.superadmin.panel import INSUFFICIENT_RIGHTS

ACCESS_DENIED = "У тебя нет доступа в админ-панель!"
NO_READY_TOURNAMENTS = "Нет турниров, готовых к закрытию."
CLOSE_TOURNAMENT_PREVIEW_CONFIRMATION = "Всё верно?"

__all__ = [
    "ACCESS_DENIED",
    "ADMIN_RESULTS_CANCELLED",
    "ADMIN_RESULTS_NOT_FOUND",
    "INSUFFICIENT_RIGHTS",
    "NO_READY_TOURNAMENTS",
    "CLOSE_TOURNAMENT_PREVIEW_CONFIRMATION",
]
