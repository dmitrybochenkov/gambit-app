from app.bot.telegram.formatters import common as fmt_common
from app.bot.telegram.formatters import tournaments as tournament_fmt


def tournament_list(page: object) -> str:
    lines = ["Выбери турнир:", ""]
    for tournament in page.items:
        lines.append(f"{tournament.id} — {tournament_fmt.label(tournament)}")
    if page.total_pages > 1:
        lines.extend(["", fmt_common.page_line(page)])
    return "\n".join(lines)


def summary(view: object) -> str:
    lines = [
        "👥 Участники турнира",
        "",
        tournament_fmt.label(view.tournament),
        "",
        f"Зарегистрированы заранее: {view.registered_count}",
        f"Пришли: {view.checked_in_count}",
        f"Ещё не отмечены: {view.unchecked_registered_count}",
        f"Без предварительной регистрации: {view.walk_in_count}",
        "",
        "Выберите тип игрока:",
    ]
    return "\n".join(lines)


def registered_confirmation(tournament: object, user: object) -> str:
    return "\n".join(
        [
            f"Добавить {user.display_name} в сегодняшний турнир?",
            "",
            tournament_fmt.type_name(tournament),
            fmt_common.date_long(tournament.date),
        ]
    )


def existing_confirmation(tournament: object, user: object) -> str:
    return "\n".join(
        [
            f"Добавить {user.display_name} в турнир без предварительной регистрации?",
            "",
            tournament_fmt.type_name(tournament),
            fmt_common.date_long(tournament.date),
        ]
    )


def new_confirmation(tournament: object, display_name: str) -> str:
    return "\n".join(
        [
            f"Создать нового игрока «{display_name}» и добавить в турнир?",
            "",
            tournament_fmt.type_name(tournament),
            fmt_common.date_long(tournament.date),
        ]
    )


def player_notification(tournament: object) -> str:
    return "\n".join(
        [
            f"✅ Вы прошли check-in на турнир «{tournament_fmt.type_name(tournament)}».",
            fmt_common.date_long(tournament.date),
        ]
    )
