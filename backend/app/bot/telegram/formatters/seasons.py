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
    lines = ["🏆 Новый сезон", ""]
    if timeline.current_season is not None:
        lines.extend(["Текущий сезон:", timeline.current_season.name])
        if timeline.current_season.ends_at is None:
            lines.append(f"с {fmt_common.date_long(timeline.current_season.starts_at)}")
            lines.append("без даты окончания")
        else:
            lines.append(f"до {fmt_common.date_long(timeline.current_season.ends_at)}")
    else:
        lines.append("Текущего сезона нет.")

    nearest_future = timeline.nearest_future_season
    last_future = timeline.last_future_season
    if nearest_future is None:
        lines.extend(["", "Можно создать следующий сезон."])
    elif last_future is not None and last_future.ends_at is None:
        lines.extend(
            [
                "",
                "Уже есть будущий открытый сезон:",
                "",
                last_future.name,
                f"с {fmt_common.date_long(last_future.starts_at)}",
                "",
                "Сначала измени его или определи границу следующего сезона.",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "Уже запланирован следующий сезон:",
                nearest_future.name,
                f"с {fmt_common.date_long(nearest_future.starts_at)}",
            ]
        )

    if timeline.pending_proposal is not None:
        lines.extend(["", "Есть черновик нового сезона."])
    return "\n".join(lines)


def list_page(page: object) -> str:
    lines = ["📋 Сезоны"]
    for season in page.items:
        lines.extend(["", season.name, _season_period(season), _season_state(season)])
    if page.total_pages > 1:
        lines.extend(["", f"{page.page + 1}/{page.total_pages}"])
    return "\n".join(lines)


def future_edit(season: object) -> str:
    return "\n".join(["✏️ Будущий сезон", "", season.name, _season_period(season)])


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
