from app.bot.telegram.formatters import common as fmt_common
from app.bot.telegram.texts.user import hall_of_fame as hall_texts


def message(seasons: list) -> str:
    lines = [
        "🏆 Зал славы",
        "",
    ]
    if not seasons:
        lines.append(hall_texts.HALL_OF_FAME_EMPTY)
        return "\n".join(lines)

    lines.extend(
        [
            "💍 — победитель сезона",
            "💥 — лучший нокаутер сезона",
        ]
    )
    for season in seasons:
        lines.extend(["", fmt_common.markdown_escape(season.season_name)])
        lines.extend(_optional_line("💍", season.champion_display_name))
        lines.extend(_optional_line("💥", season.knockout_leader_display_name))
    return "\n".join(lines)


def _optional_line(icon: str, display_name: str | None) -> list[str]:
    if display_name is None:
        return []
    return [f"{icon} {fmt_common.markdown_escape(display_name)}"]
