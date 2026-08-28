USER_RENAME_PROMPT = "✏️ Изменить пользователя\n\nВведи имя пользователя."
USER_RENAME_NOT_FOUND = "Пользователь не найден.\n\nВведи другое имя."
USER_RENAME_RESULTS_TITLE = "Выбери пользователя:"
USER_RENAME_CANCELLED = "Отмена."
USER_RENAME_INVALID_NAME = "Имя некорректно.\n\nВведи другое имя."
USER_RENAME_OCCUPIED = "Это имя уже занято другим пользователем.\n\nВведи другое имя."
USER_RENAME_SAME_NAME = "Новое имя совпадает с текущим.\n\nВведи другое имя."
USER_RENAME_STALE = "Данные устарели. Открой переименование заново."


def new_name_prompt(display_name: str) -> str:
    return f"✏️ Изменить пользователя\n\nТекущее имя:\n{display_name}\n\nВведи новое имя."


def confirmation(old_display_name: str, new_display_name: str) -> str:
    return (
        "✏️ Изменить пользователя\n\n"
        "Изменить имя:\n\n"
        f"{old_display_name}\n\n"
        "на:\n\n"
        f"{new_display_name}?"
    )


def success(old_display_name: str, new_display_name: str) -> str:
    return f"✅ Пользователь переименован\n\n{old_display_name} → {new_display_name}"


def gender_label(gender: object) -> str:
    if gender == "male":
        return "Мужской"
    if gender == "female":
        return "Женский"
    return "Не указан"


def user_card(user: object) -> str:
    return "\n".join(
        [
            f"👤 {user.display_name}",
            "",
            f"Имя: {user.display_name}",
            f"Пол: {gender_label(user.gender)}",
        ]
    )


def gender_prompt(user: object) -> str:
    return "\n".join(
        [
            f"👤 {user.display_name}",
            "",
            f"Текущий пол: {gender_label(user.gender)}",
            "",
            "Выбери новый пол:",
        ]
    )


USER_GENDER_UPDATED = "Пол обновлён."
