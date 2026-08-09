from app.bot.telegram.formatters import common as fmt_common
from app.bot.telegram.texts.admin import calendar as calendar_texts


def proposal(proposal: object) -> str:
    lines = [
        calendar_texts.SEASON_PROPOSAL_PREVIEW_TITLE,
        "",
        f"{calendar_texts.SEASON_NAME_LABEL}: {proposal.name}",
        f"{calendar_texts.SEASON_START_LABEL}: {fmt_common.date_long(proposal.starts_at)}",
    ]
    if proposal.active_season_ends_at is not None:
        lines.extend(
            [
                "",
                f"{calendar_texts.SEASON_CURRENT_END_LABEL}: "
                f"{fmt_common.date_numeric(proposal.active_season_ends_at)}",
                f"{calendar_texts.SEASON_NEW_START_LABEL}: "
                f"{fmt_common.date_numeric(proposal.starts_at)}",
            ]
        )
    return "\n".join(lines)


def created(season: object) -> str:
    return "\n".join(
        [
            calendar_texts.SEASON_CREATED_TITLE,
            season.name,
            f"{calendar_texts.SEASON_START_LABEL}: {fmt_common.date_numeric(season.starts_at)}",
            f"{calendar_texts.SEASON_SCORING_CONFIG_LABEL}: #{season.scoring_config_id}",
        ]
    )


def management(timeline: object) -> str:
    lines = ["🏆 Сезоны", ""]
    if timeline.current_season is not None:
        lines.extend(["Текущий сезон:", timeline.current_season.name])
        if timeline.current_season.ends_at is None:
            lines.append(f"с {fmt_common.date_long(timeline.current_season.starts_at)}")
            lines.append("без даты окончания")
        else:
            lines.append(f"до {fmt_common.date_long(timeline.current_season.ends_at)}")
    else:
        lines.append("Текущего сезона нет.")

    future_season = timeline.future_season
    if future_season is None:
        lines.extend(["", "Будущий сезон отсутствует."])
    else:
        lines.extend(
            [
                "",
                "Будущий сезон:",
                "",
                future_season.name,
                f"с {fmt_common.date_long(future_season.starts_at)}",
            ]
        )

    return "\n".join(lines)


def list_page(page: object) -> str:
    lines = ["📋 Сезоны"]
    for season in page.items:
        lines.extend(["", season.name, _season_period(season), _season_state(season)])
    if page.total_pages > 1:
        lines.extend(["", f"{page.page + 1}/{page.total_pages}"])
    return "\n".join(lines)


def future_delete_confirmation(season: object) -> str:
    return "\n".join(
        [
            "Удалить будущий сезон?",
            "",
            season.name,
            "",
            "Начало:",
            fmt_common.date_long(season.starts_at),
            "",
            "Предыдущий сезон снова станет открытым.",
        ]
    )


def _season_period(season: object) -> str:
    if season.ends_at is None:
        return f"с {fmt_common.date_numeric(season.starts_at)}"
    return (
        f"{fmt_common.date_numeric(season.starts_at)} — {fmt_common.date_numeric(season.ends_at)}"
    )


def _season_state(season: object) -> str:
    if season.lifecycle_state == "completed":
        return "Завершён"
    if season.lifecycle_state == "current":
        return "Текущий"
    return "Запланирован"
