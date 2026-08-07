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
