import json
from datetime import date

from app.bot.telegram import texts
from app.services.dto import (
    AdminPromptView,
    PlayerProfileView,
    TournamentView,
)
from app.services.pagination import Page


def format_tournament_label(tournament: TournamentView) -> str:
    weekday = texts.common.WEEKDAYS[tournament.date.weekday()]
    month = texts.common.MONTHS[tournament.date.month]
    type_name = (
        tournament.tournament_type_name
        if tournament.tournament_type_name is not None
        else _fallback_tournament_type_name(tournament)
    )
    return (
        f"{weekday}, {tournament.date.day} {month} — "
        f"{type_name}"
    )


def format_tournament_schedule(tournaments: list[TournamentView]) -> str:
    if not tournaments:
        return texts.user.TOURNAMENTS_EMPTY

    lines = [texts.user.TOURNAMENT_SCHEDULE_TITLE, ""]
    for tournament in tournaments:
        capacity_text = texts.user.TOURNAMENT_CAPACITY_LABEL.format(
            capacity=tournament.capacity
        )
        lines.append(
            f"{format_tournament_label(tournament)} "
            f"({capacity_text})"
        )
    return "\n".join(lines)


def format_rating(
    title: str,
    page: Page,
    current_player_id: int,
) -> str:
    return texts.user.rating_message(title, page, current_player_id)


def format_profile(title: str, stats: PlayerProfileView | None) -> str:
    return texts.user.profile_message(title, stats)


def format_admin_calendar_prompt(prompt: AdminPromptView) -> str:
    payload = json.loads(prompt.payload)
    if prompt.kind == "season_proposal":
        starts_at = date.fromisoformat(payload["starts_at"])
        ends_at = date.fromisoformat(payload["ends_at"])
        return "\n".join(
            [
                texts.admin.SEASON_PROPOSAL_TITLE,
                "",
                f"{texts.admin.SEASON_PROPOSAL_LABEL}: {payload['name']}",
                f"{texts.admin.SEASON_PERIOD_LABEL}: "
                f"{format_date(starts_at)} — {format_date(ends_at)}",
                "",
                texts.admin.CONFIRM_CREATION_PROMPT,
            ]
        )

    lines = [texts.admin.TOURNAMENTS_PROPOSAL_TITLE, ""]
    for item in payload["tournaments"]:
        tournament = TournamentView(
            id=0,
            tournament_type_id=int(item["tournament_type_id"]),
            date=date.fromisoformat(item["date"]),
            capacity=int(item["capacity"]),
            tournament_type_name=item["tournament_type_name"],
        )
        lines.append(f"• {format_tournament_label(tournament)}")
    lines.extend(["", texts.admin.CONFIRM_CREATION_PROMPT])
    return "\n".join(lines)


def format_date(value: date) -> str:
    return f"{value.day} {texts.common.MONTHS[value.month]} {value.year}"


def _fallback_tournament_type_name(tournament: TournamentView) -> str:
    type_id = tournament.tournament_type_id
    return texts.user.TOURNAMENT_TYPE_FALLBACK.format(type_id=type_id)
