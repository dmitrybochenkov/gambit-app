ADMIN_ADD_NO_CANDIDATES = "Некого назначать админом."
ADMIN_ADD_SEARCH_PROMPT = "Введи ник игрока"
ADMIN_ADD_NOT_FOUND = "Игроки не найдены.\n\nПопробуй ввести другое имя."
ADMIN_ADD_RESULTS_TITLE = "Выбери игрока:"
ADMIN_ADD_CONFIRMATION = "Назначить администратором:\n\n{display_name}?"
ADMIN_ADDED = "✅ {display_name} назначен администратором."
ADMIN_ADDED_FOR_PLAYER = "Тебе назначена роль админа."
ADMIN_ALREADY_ASSIGNED = "Игрок уже админ."
PLAYER_NOT_FOUND = "Игрок не найден."
ADMIN_ADD_CANCELLED = "Отмена."


def candidate_search_results() -> str:
    return ADMIN_ADD_RESULTS_TITLE


def add_confirmation(display_name: str) -> str:
    return ADMIN_ADD_CONFIRMATION.format(display_name=display_name)


def admin_added(display_name: str) -> str:
    return ADMIN_ADDED.format(display_name=display_name)
