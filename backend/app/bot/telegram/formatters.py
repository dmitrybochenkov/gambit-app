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

    lines = [texts.admin.TOURNAMENTS_MANUAL_PROPOSAL_TITLE, ""]
    for item in payload["tournaments"]:
        lines.extend(_format_tournament_proposal_item(item))
        lines.append("")
    if lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def format_manual_season_prompt(prompt: AdminPromptView) -> str:
    payload = json.loads(prompt.payload)
    starts_at = date.fromisoformat(payload["starts_at"])
    ends_at = date.fromisoformat(payload["ends_at"])
    return "\n".join(
        [
            texts.admin.SEASON_MANUAL_PROPOSAL_TITLE,
            payload["name"],
            f"{texts.admin.SEASON_PERIOD_LABEL}: "
            f"{format_numeric_date(starts_at)} — {format_numeric_date(ends_at)}",
        ]
    )


def format_created_season_prompt(prompt: AdminPromptView) -> str:
    payload = json.loads(prompt.payload)
    starts_at = date.fromisoformat(payload["starts_at"])
    ends_at = date.fromisoformat(payload["ends_at"])
    return "\n".join(
        [
            texts.admin.SEASON_CREATED_TITLE,
            payload["name"],
            f"{texts.admin.SEASON_PERIOD_LABEL}: "
            f"{format_numeric_date(starts_at)} — {format_numeric_date(ends_at)}",
        ]
    )


def format_created_tournaments_prompt(prompt: AdminPromptView) -> str:
    payload = json.loads(prompt.payload)
    lines = [texts.admin.TOURNAMENTS_CREATED_TITLE, ""]
    for item in payload["tournaments"]:
        lines.extend(_format_tournament_proposal_item(item))
        lines.append("")
    if lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def format_date(value: date) -> str:
    return f"{value.day} {texts.common.MONTHS[value.month]} {value.year}"


def format_numeric_date(value: date) -> str:
    return f"{value.day}.{value.month:02d}.{value.year}"


def format_number(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def _format_tournament_proposal_item(item: dict[str, object]) -> list[str]:
    tournament = TournamentView(
        id=0,
        tournament_type_id=int(item["tournament_type_id"]),
        date=date.fromisoformat(str(item["date"])),
        capacity=int(item["capacity"]),
        tournament_type_name=str(item["tournament_type_name"]),
    )
    rebuys = item.get("rebuys", [])
    rebuy_fees = " / ".join(format_number(int(rebuy["fee"])) for rebuy in rebuys)
    rebuy_stacks = " / ".join(format_number(int(rebuy["stack"])) for rebuy in rebuys)
    return [
        f"• {format_tournament_label(tournament)}",
        texts.admin.TOURNAMENT_ENTRY_LABEL,
        (
            f"{format_number(int(item['entry_fee']))} ₽ — "
            f"{format_number(int(item['entry_stack']))} фишек"
        ),
        texts.admin.TOURNAMENT_REBUYS_LABEL,
        f"{rebuy_fees} ₽" if rebuy_fees else "—",
        f"{rebuy_stacks} фишек" if rebuy_stacks else "—",
        texts.admin.TOURNAMENT_ADDON_LABEL,
        (
            f"{format_number(int(item['addon_fee']))} ₽ — "
            f"{format_number(int(item['addon_stack']))} фишек"
        ),
    ]


def _fallback_tournament_type_name(tournament: TournamentView) -> str:
    type_id = tournament.tournament_type_id
    return texts.user.TOURNAMENT_TYPE_FALLBACK.format(type_id=type_id)
