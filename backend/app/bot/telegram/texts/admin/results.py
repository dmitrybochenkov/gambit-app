ADMIN_RESULTS_NO_TOURNAMENTS = "На сегодня нет активного турнира."
ADMIN_RESULTS_PLAYERS_TITLE = "Игроки турнира"
ADMIN_RESULTS_PLAYERS_EMPTY = "Результаты еще не внесены."
ADMIN_RESULTS_MANUAL_VALUE_PROMPTS = {
    "ko": "Введи количество 🥊 числом.",
    "big": "Введи количество 👑🥊 числом.",
    "bonus": "Введи бонусные очки числом.",
    "place": "Введи место числом от 1 до 5.",
}
ADMIN_RESULTS_INVALID_MANUAL_VALUE = {
    "ko": "🥊 должно быть неотрицательным числом.",
    "big": "👑🥊 должно быть неотрицательным числом.",
    "bonus": "Бонус должен быть неотрицательным числом.",
    "place": "Место должно быть числом от 1 до 5.",
}
ADMIN_RESULTS_SAVED = "Результат сохранен."
ADMIN_RESULTS_CLOSED = "Турнир закрыт."
ADMIN_RESULTS_CHECK_FAILED = "Нужно поправить:\n{errors}"
ADMIN_RESULTS_CHECK_FAILED_SHORT = "Нужно поправить ошибки."
ADMIN_RESULTS_CANCELLED = "Отмена."
ADMIN_RESULTS_NOT_FOUND = "Турнир не найден или уже закрыт."
PLAYER_NOT_FOUND = "Игрок не найден."


def admin_result_check_failed(errors: list[str]) -> str:
    return ADMIN_RESULTS_CHECK_FAILED.format(errors="\n".join(f"• {error}" for error in errors))
