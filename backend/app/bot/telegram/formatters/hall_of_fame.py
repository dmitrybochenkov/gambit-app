from app.bot.telegram.formatters import common as fmt_common
from app.bot.telegram.keyboards.superadmin.hall_of_fame import HallOfFameField


def season_list(page: object) -> str:
    lines = ["🔧 Наполнить зал славы"]
    if page.total_items <= 0:
        lines.extend(["", "Завершённых сезонов нет."])
        return "\n".join(lines)
    lines.extend(["", "Выбери завершённый сезон:"])
    if page.total_pages > 1:
        lines.extend(["", fmt_common.page_line(page)])
    return "\n".join(lines)


def season_card(entry: object) -> str:
    return "\n".join(
        [
            "🏆 Зал славы",
            fmt_common.markdown_escape(entry.season_name),
            "",
            "💍 Чемпион:",
            _display_name(entry.champion),
            "",
            "💥 Нокаутер:",
            _display_name(entry.knockout_leader),
        ]
    )


def search_prompt(field: HallOfFameField) -> str:
    if field == HallOfFameField.CHAMPION:
        return "Введи имя чемпиона сезона."
    return "Введи имя нокаутера сезона."


def search_results(candidates: list[object]) -> str:
    if not candidates:
        return "Игроки не найдены."
    return "Выбери игрока:"


def confirmation(*, field: HallOfFameField, player: object, season_name: str) -> str:
    role = "чемпионом" if field == HallOfFameField.CHAMPION else "нокаутером"
    return "\n".join(
        [
            f"Назначить {role} сезона:",
            "",
            fmt_common.markdown_escape(player.display_name),
            "",
            f"{fmt_common.markdown_escape(season_name)}?",
        ]
    )


def _display_name(user: object | None) -> str:
    if user is None:
        return "Не выбран"
    return fmt_common.markdown_escape(user.display_name)
