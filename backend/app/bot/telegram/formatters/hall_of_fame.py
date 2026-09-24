from app.bot.telegram.formatters import common as fmt_common
from app.bot.telegram.formatters.statistics.achievements import achievement_emoji
from app.bot.telegram.keyboards.superadmin.hall_of_fame import HallOfFameField


def season_list(page: object) -> str:
    lines = ["🔧 Наполнить зал славы"]
    if page.total_items <= 0:
        lines.extend(["", "Сезонов нет."])
        return "\n".join(lines)
    lines.extend(["", "Выбери сезон:"])
    if page.total_pages > 1:
        lines.extend(["", fmt_common.page_line(page)])
    return "\n".join(lines)


def season_card(entry: object) -> str:
    lines = [
        "🏆 Зал славы",
        fmt_common.markdown_escape(entry.season_name),
        f"📸 Фото: {len(entry.photos)}",
    ]
    for achievement in entry.achievements:
        lines.extend(
            [
                "",
                f"{achievement_emoji(achievement.kind)} "
                f"{fmt_common.markdown_escape(achievement.player.display_name)} "
                f"({achievement.awarded_at:%d.%m.%Y})",
            ]
        )
    return "\n".join(lines)


def search_prompt(field: HallOfFameField) -> str:
    return "Введи имя обладателя достижения."


def photo_prompt(*, season_name: str) -> str:
    return "\n".join(
        [
            "📸 Фото Зала славы",
            "",
            f"Пришли одну фотографию для сезона «{season_name}».",
        ]
    )


def photo_confirmation(*, season_name: str) -> str:
    return f"Добавить это фото для сезона «{season_name}»?"


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
