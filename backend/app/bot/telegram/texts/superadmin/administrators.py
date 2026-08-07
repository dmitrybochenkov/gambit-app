ADMIN_ADD_NO_CANDIDATES = "Некого назначать админом."
ADMIN_ADD_LIST_TITLE = "Кого назначаем админом?"
ADMIN_ADD_CONFIRMATION = "Сделать админом: {display_name}?"
ADMIN_ADDED = "Админ добавлен."
ADMIN_ADDED_FOR_PLAYER = "Тебе назначена роль админа."
ADMIN_ALREADY_ASSIGNED = "Игрок уже админ."
PLAYER_NOT_FOUND = "Игрок не найден."


def candidate_list(page: object) -> str:
    lines = [ADMIN_ADD_LIST_TITLE, ""]
    for player in page.items:
        lines.append(f"{player.id} — {player.display_name}")
    return "\n".join(lines)


def add_confirmation(display_name: str) -> str:
    return ADMIN_ADD_CONFIRMATION.format(display_name=display_name)
