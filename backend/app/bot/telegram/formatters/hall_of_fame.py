from collections.abc import Iterable
from typing import Any

from app.bot.telegram.formatters import common as fmt_common
from app.bot.telegram.formatters.statistics.achievements import (
    achievement_emoji,
    achievement_shows_date,
)
from app.bot.telegram.keyboards.superadmin.hall_of_fame import HallOfFameField


def season_list(page: object) -> str:
    lines = ["🏆 Наполнение Зала славы"]
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
    lines.extend(_achievement_lines(entry.achievements))
    return "\n".join(lines)


def achievements_menu(entry: object) -> str:
    return achievement_context(entry)


def achievement_context(entry: object) -> str:
    return "\n".join(
        [
            "🏆 Награды",
            fmt_common.markdown_escape(entry.season_name),
            *_achievement_lines(entry.achievements),
        ]
    )


def date_prompt(entry: object, field: HallOfFameField) -> str:
    return f"{achievement_context(entry)}\n\nВведи дату для {_achievement_label(field)}"


def player_prompt(entry: object, field: HallOfFameField, awarded_at: object) -> str:
    return (
        f"{achievement_context(entry)}\n\n"
        f"Введи имя для {_achievement_label(field)} ({awarded_at:%d.%m.%Y})"
    )


def photo_menu(entry: object) -> str:
    return (
        f"📸 Фото Зала славы\n{fmt_common.markdown_escape(entry.season_name)}\n"
        f"Загружено: {len(entry.photos)}"
    )


def achievement_confirmation(
    *,
    entry: object,
    field: HallOfFameField,
    player: object,
    awarded_at: object,
    existing: object | None,
) -> str:
    label = _achievement_label(field)
    player_name = fmt_common.markdown_escape(player.display_name)
    if existing is None:
        return (
            f"{achievement_context(entry)}\n\nПодтверди назначение:\n"
            f"{label} ({awarded_at:%d.%m.%Y}) — {player_name}"
        )
    return "\n".join(
        [
            achievement_context(entry),
            "",
            "Подтверди изменение:",
            "",
            "Было:",
            f"{achievement_emoji(existing.kind)} "
            f"{fmt_common.markdown_escape(existing.player.display_name)} "
            f"({existing.awarded_at:%d.%m.%Y})",
            "Станет:",
            f"{achievement_emoji(existing.kind)} {player_name} ({awarded_at:%d.%m.%Y})",
        ]
    )


def delete_menu(entry: object) -> str:
    return "\n".join(
        [
            "🗑 Удаление награды",
            fmt_common.markdown_escape(entry.season_name),
            "",
            *_achievement_lines(entry.achievements),
        ]
    )


def delete_confirmation(achievement: object) -> str:
    return "\n".join(
        [
            "🗑 Удалить награду?",
            "",
            f"{_achievement_label(HallOfFameField(achievement.kind.value))} "
            f"({achievement.awarded_at:%d.%m.%Y}) — "
            f"{fmt_common.markdown_escape(achievement.player.display_name)}",
        ]
    )


def _achievement_label(field: HallOfFameField) -> str:
    return {
        HallOfFameField.RATING_WINNER: "💍 Победитель рейтинга",
        HallOfFameField.KO_RATING_WINNER: "💥 Победитель KO-рейтинга",
        HallOfFameField.GRAND_SEASON: "🏆 Grand Season",
        HallOfFameField.GRAND_MONTH: "🏅 Grand Month",
        HallOfFameField.GRAND_KNOCKOUT: "🥊 Grand Knockout",
    }[field]


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


def _achievement_lines(achievements: Iterable[Any]) -> list[str]:
    lines = []
    for achievement in achievements:
        suffix = (
            f" ({achievement.awarded_at:%d.%m.%Y})"
            if achievement_shows_date(achievement.kind)
            else ""
        )
        lines.append(
            f"{achievement_emoji(achievement.kind)} "
            f"{fmt_common.markdown_escape(achievement.player.display_name)}{suffix}"
        )
    return lines
