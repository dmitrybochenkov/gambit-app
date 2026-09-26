from app.bot.telegram.formatters import common as fmt_common
from app.bot.telegram.formatters.statistics.achievements import (
    ACHIEVEMENT_KIND_ORDER,
    achievement_shows_date,
)
from app.bot.telegram.texts.user import hall_of_fame as hall_texts


def message(seasons: list) -> str:
    lines = ["🏆 Зал славы"]
    achievement_types_by_kind = {
        str(achievement.kind): (achievement.emoji, achievement.title)
        for season in seasons
        for achievement in season.achievements
    }
    if achievement_types_by_kind:
        lines.extend(
            [
                "",
                *(
                    f"{achievement_types_by_kind[kind][0]} - "
                    f"{_lowercase_first(achievement_types_by_kind[kind][1])}"
                    for kind in ACHIEVEMENT_KIND_ORDER
                    if kind in achievement_types_by_kind
                ),
            ]
        )
    if not seasons:
        lines.extend(["", hall_texts.HALL_OF_FAME_EMPTY])
    return "\n".join(lines)


def season_caption(season: object) -> str:
    lines = [fmt_common.markdown_escape(season.season_name)]
    for achievement in season.achievements:
        suffix = (
            f" ({achievement.awarded_at:%d.%m.%Y})"
            if achievement_shows_date(achievement.kind)
            else ""
        )
        lines.append(
            f"{achievement.emoji} {fmt_common.markdown_escape(achievement.display_name)}{suffix}"
        )
    return "\n".join(lines)


def _lowercase_first(value: str) -> str:
    return value[:1].lower() + value[1:]


def _optional_line(icon: str, display_name: str | None) -> list[str]:
    if display_name is None:
        return []
    return [f"{icon} {fmt_common.markdown_escape(display_name)}"]
