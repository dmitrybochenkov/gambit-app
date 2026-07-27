from datetime import date

from app.bot.telegram import texts
from app.services.dto import (
    PlayerProfileView,
    ScoringConfigView,
    SeasonView,
    TournamentPromptItemView,
    TournamentPromptView,
    TournamentResultDraftPlayerView,
    TournamentResultDraftView,
    TournamentView,
    UserView,
)
from app.services.pagination import Page

PLACE_EMOJIS = {
    1: "1️⃣",
    2: "2️⃣",
    3: "3️⃣",
    4: "4️⃣",
    5: "5️⃣",
}


def format_tournament_label(tournament: TournamentView) -> str:
    weekday = texts.common.WEEKDAYS[tournament.date.weekday()]
    month = texts.common.MONTHS[tournament.date.month]
    type_name = (
        tournament.tournament_type_name
        if tournament.tournament_type_name is not None
        else _fallback_tournament_type_name(tournament)
    )
    return f"{weekday}, {tournament.date.day} {month} — {type_name}"


def format_tournament_schedule(tournaments: list[TournamentView]) -> str:
    if not tournaments:
        return texts.user.TOURNAMENTS_EMPTY

    lines = [texts.user.TOURNAMENT_SCHEDULE_TITLE, ""]
    for tournament in tournaments:
        lines.append(f"• {format_tournament_label(tournament)}")
    return "\n".join(lines)


def format_rating(
    title: str,
    page: Page,
    current_player_id: int,
) -> str:
    return texts.user.rating_message(title, page, current_player_id)


def format_profile(title: str, stats: PlayerProfileView | None) -> str:
    return texts.user.profile_message(title, stats)


def format_admin_calendar_prompt(prompt: TournamentPromptView) -> str:
    lines = [texts.admin.TOURNAMENTS_MANUAL_PROPOSAL_TITLE, ""]
    for item in prompt.tournaments:
        lines.extend(_format_tournament_proposal_item(item))
        lines.append("")
    if lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def format_admin_result_tournament_list(page: Page[TournamentView]) -> str:
    lines = [texts.admin.ADMIN_RESULTS_TOURNAMENT_LIST_TITLE, ""]
    for tournament in page.items:
        lines.append(f"{tournament.id} — {format_tournament_label(tournament)}")
    if page.total_pages > 1:
        lines.extend(["", _page_line(page)])
    return "\n".join(lines)


def format_admin_result_menu(draft: TournamentResultDraftView) -> str:
    pool = format_decimal(draft.points_pool) if draft.points_pool is not None else "не введен"
    lines = [
        texts.admin.ADMIN_RESULTS_MENU_TITLE,
        format_tournament_label(draft.tournament),
        f"Пул: {pool}",
    ]
    lines.extend(_admin_result_summary_lines(draft))
    lines.extend(["", f"Игроков: {len(draft.players)}"])
    return "\n".join(lines)


def format_admin_result_close_confirmation(draft: TournamentResultDraftView) -> str:
    pool = format_decimal(draft.points_pool) if draft.points_pool is not None else "не введен"
    lines = [
        "Подтверди закрытие турнира",
        format_tournament_label(draft.tournament),
        f"Пул: {pool}",
        "",
        "Результаты:",
    ]
    for player in draft.players:
        result = _admin_result_confirmation(player, draft)
        line = f"• {player.display_name}"
        if result:
            line += f": {result}"
        lines.append(line)
    return "\n".join(lines)


def format_admin_result_players(
    draft: TournamentResultDraftView,
    _page: Page,
) -> str:
    lines = [
        texts.admin.ADMIN_RESULTS_PLAYERS_TITLE,
        format_tournament_label(draft.tournament),
        "",
    ]
    lines.extend(_admin_result_summary_lines(draft))
    return "\n".join(lines)


def _admin_result_player_has_value(player: TournamentResultDraftPlayerView) -> bool:
    return player.place is not None or player.knockouts_count > 0 or player.big_knockouts_count > 0


def _admin_result_summary_lines(draft: TournamentResultDraftView) -> list[str]:
    lines = _admin_result_places_table_lines(draft)
    knockout_lines = _admin_result_knockout_lines(draft)
    if knockout_lines:
        lines.extend(["", *knockout_lines])
    return lines


def _admin_result_places_table_lines(draft: TournamentResultDraftView) -> list[str]:
    players_by_place = {
        player.place: player
        for player in sorted(draft.players, key=lambda player: player.display_name.casefold())
        if player.place is not None
    }
    rows = ["| Место | Игрок", "| ----- | -----"]
    for place in range(1, 6):
        player = players_by_place.get(place)
        display_name = player.display_name if player is not None else "НЕ ВВЕДЕНО"
        rows.append(f"| {place:>5} | {display_name}")
    return ["```", *rows, "```"]


def _admin_result_knockout_lines(draft: TournamentResultDraftView) -> list[str]:
    if draft.knockout_mode not in {"small", "small_big"}:
        return []

    players = sorted(
        [
            player
            for player in draft.players
            if player.knockouts_count > 0 or player.big_knockouts_count > 0
        ],
        key=_admin_result_player_sort_key,
    )
    if not players:
        return []

    lines = ["🥊:"]
    for player in players:
        result_parts = _admin_result_player_parts(
            knockout_mode=draft.knockout_mode,
            knockouts_count=player.knockouts_count,
            big_knockouts_count=player.big_knockouts_count,
            place=None,
        )
        lines.append(f"{_markdown_escape(player.display_name)}: {', '.join(result_parts)}")
    return lines


def _markdown_escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("_", "\\_")
        .replace("*", "\\*")
        .replace("`", "\\`")
        .replace("[", "\\[")
    )


def _admin_result_player_sort_key(
    player: TournamentResultDraftPlayerView,
) -> tuple[int, int, int, str]:
    return (
        -player.big_knockouts_count,
        -player.knockouts_count,
        player.place if player.place is not None else 99,
        player.display_name.casefold(),
    )


def _admin_result_player_parts(
    *,
    knockout_mode: str,
    knockouts_count: int,
    big_knockouts_count: int,
    place: int | None,
) -> list[str]:
    place_part = [_place_label(place)] if place is not None else []
    if knockout_mode == "small_big":
        return [
            f"💥🥊 х{big_knockouts_count}",
            f"🥊 х{knockouts_count}",
            *place_part,
        ]
    if knockout_mode == "small":
        return [f"🥊 х{knockouts_count}", *place_part]
    return place_part


def _place_label(place: int) -> str:
    return PLACE_EMOJIS.get(place, str(place))


def _admin_result_confirmation(
    player: TournamentResultDraftPlayerView,
    draft: TournamentResultDraftView,
) -> str:
    result_parts = []
    if player.place is not None:
        result_parts.append(_place_label(player.place))
    if draft.knockout_mode == "small_big" and player.big_knockouts_count > 0:
        result_parts.append(f"💥🥊 х{player.big_knockouts_count}")
    if draft.knockout_mode in {"small", "small_big"} and player.knockouts_count > 0:
        result_parts.append(f"🥊 х{player.knockouts_count}")
    return " | ".join(result_parts)


def format_admin_result_player_detail(
    draft: TournamentResultDraftView,
    player: TournamentResultDraftPlayerView,
) -> str:
    lines = [
        "Результат игрока",
        player.display_name,
    ]
    if draft.knockout_mode in {"small", "small_big"}:
        label = "🥊"
        lines.append(f"{label}: {player.knockouts_count}")
    if draft.knockout_mode == "small_big":
        lines.append(f"💥🥊: {player.big_knockouts_count}")
    if player.place is not None:
        lines.append(f"Место: {_place_label(player.place)}")
    return "\n".join(lines)


def format_admin_result_field_prompt(
    player: TournamentResultDraftPlayerView,
    field_name: str,
) -> str:
    return f"{player.display_name}\n\nВыбери {field_name}:"


def format_admin_tournament_registration_tournament_list(
    page: Page[TournamentView],
) -> str:
    lines = [texts.admin.ADMIN_TOURNAMENT_REGISTRATION_TOURNAMENT_LIST_TITLE, ""]
    for tournament in page.items:
        lines.append(f"{tournament.id} — {format_tournament_label(tournament)}")
    if page.total_pages > 1:
        lines.extend(["", _page_line(page)])
    return "\n".join(lines)


def format_admin_tournament_registration_player_list(
    tournament: TournamentView,
    page: Page[UserView],
    title: str | None = None,
) -> str:
    lines = [
        title or texts.admin.ADMIN_TOURNAMENT_REGISTRATION_PLAYER_LIST_TITLE,
        format_tournament_label(tournament),
        "",
    ]
    for player in page.items:
        lines.append(f"{player.id} — {player.display_name}")
    if page.total_pages > 1:
        lines.extend(["", _page_line(page)])
    return "\n".join(lines)


def format_season_open_confirmation(
    *,
    name: str,
    starts_at: date,
    scoring_config: ScoringConfigView,
) -> str:
    return "\n".join(
        [
            texts.admin.SEASON_MANUAL_PROPOSAL_TITLE,
            name,
            f"{texts.admin.SEASON_START_LABEL}: {format_numeric_date(starts_at)}",
            f"{texts.admin.SEASON_SCORING_CONFIG_LABEL}: "
            f"{format_scoring_config_label(scoring_config)}",
            "",
            texts.admin.SEASON_ACTIVE_CLOSE_WARNING,
        ]
    )


def format_created_season(season: SeasonView) -> str:
    return "\n".join(
        [
            texts.admin.SEASON_CREATED_TITLE,
            season.name,
            f"{texts.admin.SEASON_START_LABEL}: {format_numeric_date(season.starts_at)}",
            f"{texts.admin.SEASON_SCORING_CONFIG_LABEL}: #{season.scoring_config_id}",
        ]
    )


def format_scoring_config_label(config: ScoringConfigView) -> str:
    return (
        f"#{config.id}: 🥊 {config.knockout_small_points} | "
        f"💥🥊 {config.knockout_big_points}"
    )


def format_created_tournaments_prompt(prompt: TournamentPromptView) -> str:
    lines = [texts.admin.TOURNAMENTS_CREATED_TITLE, ""]
    for item in prompt.tournaments:
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


def format_decimal(value: object) -> str:
    text = f"{value}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _page_line(page: Page) -> str:
    start = page.page * page.page_size + 1
    end = start + len(page.items) - 1
    return f"{start}-{end} из {page.total_items}"


def _format_tournament_proposal_item(item: TournamentPromptItemView) -> list[str]:
    tournament = TournamentView(
        id=0,
        tournament_type_id=item.tournament_type.id,
        date=item.date,
        tournament_type_name=item.tournament_type.name,
    )
    rebuy_fees = " / ".join(format_number(rebuy.fee) for rebuy in item.tournament_type.rebuys)
    rebuy_stacks = " / ".join(format_number(rebuy.stack) for rebuy in item.tournament_type.rebuys)
    lines = [
        f"• {format_tournament_label(tournament)}",
        texts.admin.TOURNAMENT_ENTRY_LABEL,
        (
            f"{format_number(item.tournament_type.entry_fee)} ₽ — "
            f"{format_number(item.tournament_type.entry_stack)} фишек"
        ),
        texts.admin.TOURNAMENT_REBUYS_LABEL,
        f"{rebuy_fees} ₽" if rebuy_fees else "—",
        f"{rebuy_stacks} фишек" if rebuy_stacks else "—",
        texts.admin.TOURNAMENT_ADDON_LABEL,
        (
            f"{format_number(item.tournament_type.addon_fee)} ₽ — "
            f"{format_number(item.tournament_type.addon_stack)} фишек"
        ),
    ]
    if item.tournament_type.description:
        lines.extend(["", item.tournament_type.description])
    if item.tournament_type.knockout_mode != "none":
        lines.extend(["", f"🥊: {item.tournament_type.knockout_mode}"])
    return lines


def _fallback_tournament_type_name(tournament: TournamentView) -> str:
    type_id = tournament.tournament_type_id
    return texts.user.TOURNAMENT_TYPE_FALLBACK.format(type_id=type_id)
