HALL_OF_FAME_CANCELLED = "Отмена."
HALL_OF_FAME_NO_COMPLETED_SEASONS = "Завершённых сезонов нет."
HALL_OF_FAME_SEASON_NOT_FOUND = "Сезон не найден."
HALL_OF_FAME_PLAYER_NOT_FOUND = "Игрок не найден."
HALL_OF_FAME_SEARCH_EMPTY = "Игроки не найдены."
HALL_OF_FAME_CHAMPION_PROMPT = "Введи имя чемпиона сезона."
HALL_OF_FAME_KNOCKOUT_PROMPT = "Введи имя нокаутера сезона."


def saved_champion(display_name: str, season_name: str) -> str:
    return f"✅ Чемпион сохранён\n\n{display_name}\n{season_name}"


def saved_knockout(display_name: str, season_name: str) -> str:
    return f"✅ Нокаутер сохранён\n\n{display_name}\n{season_name}"
