USER_RENAME_PROMPT = "✏️ Переименовать пользователя\n\nВведи имя пользователя."
USER_RENAME_NOT_FOUND = "Пользователь не найден.\n\nВведи другое имя."
USER_RENAME_RESULTS_TITLE = "Выбери пользователя:"
USER_RENAME_CANCELLED = "Отмена."
USER_RENAME_INVALID_NAME = "Имя некорректно.\n\nВведи другое имя."
USER_RENAME_OCCUPIED = "Это имя уже занято другим пользователем.\n\nВведи другое имя."
USER_RENAME_SAME_NAME = "Новое имя совпадает с текущим.\n\nВведи другое имя."
USER_RENAME_STALE = "Данные устарели. Открой переименование заново."


def new_name_prompt(display_name: str) -> str:
    return f"✏️ Переименовать пользователя\n\nТекущее имя:\n{display_name}\n\nВведи новое имя."


def confirmation(old_display_name: str, new_display_name: str) -> str:
    return (
        "✏️ Переименовать пользователя\n\n"
        "Изменить имя:\n\n"
        f"{old_display_name}\n\n"
        "на:\n\n"
        f"{new_display_name}?"
    )


def success(old_display_name: str, new_display_name: str) -> str:
    return f"✅ Пользователь переименован\n\n{old_display_name} → {new_display_name}"
