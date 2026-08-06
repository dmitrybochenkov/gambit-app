import json
from datetime import date

from app.bot.telegram import texts
from app.services.dto import (
    HallOfFameSeasonView,
    HistoricalTournamentResultRowView,
    HistoricalTournamentResultView,
    HistoricalTournamentView,
    HistoryMonthView,
    HistoryYearView,
    PlayerProfileView,
    SeasonProposalView,
    SeasonView,
    TournamentCheckInView,
    TournamentPromptItemView,
    TournamentPromptView,
    TournamentResultPlayerView,
    TournamentResultsView,
    TournamentView,
    UserView,
    WeeklyScheduleTournamentView,
    WeeklyScheduleView,
)
from app.services.pagination import Page

TELEGRAM_MESSAGE_LIMIT = 4096
WEEKLY_SCHEDULE_HEADER = "🔥 РАСПИСАНИЕ ТУРНИРОВ ПОКЕРНОГО КЛУБА «ГАМБИТ»\n🔥♠️♥️♣️♦️"
WEEKLY_SCHEDULE_SEPARATOR = "━━━━━━━━━━━━━━"
PUBLIC_TOURNAMENT_DESCRIPTIONS = {
    "bounty": [
        "💀 Динамические нокауты",
        "• До финального стола — 15 очков за нокаут",
        "• На финальном столе — 60 очков за нокаут",
    ],
    "classic": ["Дополнительные бонусы за комбинации"],
    "freezeout": [
        "🎯 Формат для самых скиловых игроков",
        "• Бесплатный напиток из перечня",
    ],
    "double_double": [
        "⚡️ Удвоенный рейтинг",
        "⚡️ Увеличенные стартовые стеки",
    ],
    "mystery_bounty": [
        "🎁 Награды за нокауты",
        "• Очки в рейтинг",
        "• Привилегии клуба",
        "• Дополнительные фишки",
    ],
    "boss_bounty": [
        "👑 Охота на Босса",
        "• Нокаут Босса — 60 очков в рейтинг",
        "• Босс получает +10 000 фишек к следующему ребаю",
        "• Боссом становится лучший нокаутер предыдущего Баунти-турнира",
    ],
}
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
    type_name = _tournament_type_name(tournament)
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


def format_history_years(page: Page[HistoryYearView]) -> str:
    lines = [texts.user.HISTORY_YEARS_PROMPT]
    if not page.items:
        lines.extend(["", texts.user.HISTORY_EMPTY])
    elif page.total_pages > 1:
        lines.extend(["", _page_line(page)])
    return "\n".join(lines)


def format_history_months(
    year: int,
    page: Page[HistoryMonthView],
) -> str:
    lines = [texts.user.HISTORY_MONTHS_PROMPT, f"{year} год"]
    if page.total_pages > 1:
        lines.extend(["", _page_line(page)])
    return "\n".join(lines)


def format_history_tournaments(
    year: int,
    month: int,
    page: Page[HistoricalTournamentView],
) -> str:
    lines = [
        texts.user.HISTORY_TOURNAMENTS_PROMPT,
        f"{_month_name(month)} {year}",
    ]
    if page.total_pages > 1:
        lines.extend(["", _page_line(page)])
    return "\n".join(lines)


def format_historical_tournament_result(
    result: HistoricalTournamentResultView,
    page: Page[HistoricalTournamentResultRowView],
) -> str:
    tournament = result.tournament
    lines = [
        "⏳ История",
        "",
        format_date(tournament.date),
        _markdown_escape(tournament.tournament_name),
        "",
        "```",
        *_historical_result_table_lines(page.items),
        "```",
    ]
    if page.total_pages > 1:
        lines.extend(["", _page_line(page)])
    return "\n".join(lines)


def format_hall_of_fame(seasons: list[HallOfFameSeasonView]) -> str:
    lines = [
        "🏆 Зал славы",
        "",
    ]
    if not seasons:
        lines.append(texts.user.HALL_OF_FAME_EMPTY)
        return "\n".join(lines)

    lines.extend(
        [
            "💍 — победитель сезона",
            "🥊 — лучший нокаутер сезона",
        ]
    )
    for season in seasons:
        lines.extend(
            [
                "",
                _markdown_escape(season.season_name),
                _hall_of_fame_line("💍", season.champion_display_name),
                _hall_of_fame_line("🥊", season.knockout_leader_display_name),
            ]
        )
    return "\n".join(lines)


def format_admin_calendar_prompt(prompt: TournamentPromptView) -> str:
    lines = [texts.admin.TOURNAMENTS_MANUAL_PROPOSAL_TITLE, ""]
    for item in prompt.tournaments:
        lines.append(_format_tournament_prompt_item_label(item))
    return "\n".join(lines)


def format_public_weekly_schedule(schedule: WeeklyScheduleView) -> list[str]:
    blocks = [
        _format_public_weekly_schedule_tournament(tournament)
        for tournament in sorted(schedule.tournaments, key=lambda item: (item.date, item.id))
    ]
    return _split_weekly_schedule_messages(blocks)


def format_admin_result_tournament_list(page: Page[TournamentView]) -> str:
    lines = [texts.admin.ADMIN_RESULTS_TOURNAMENT_LIST_TITLE, ""]
    for tournament in page.items:
        lines.append(f"{tournament.id} — {format_tournament_label(tournament)}")
    if page.total_pages > 1:
        lines.extend(["", _page_line(page)])
    return "\n".join(lines)


def format_admin_result_menu(results: TournamentResultsView) -> str:
    fund = (
        format_decimal(results.tournament_fund)
        if results.tournament_fund is not None
        else "не введен"
    )
    lines = [
        texts.admin.ADMIN_RESULTS_MENU_TITLE,
        format_tournament_label(results.tournament),
        f"Фонд турнира: {fund}",
        f"Игроки: {results.checked_in_count or len(results.players)}",
        f"В работе: {len(results.players)}",
    ]
    lines.extend(_admin_result_summary_lines(results))
    return "\n".join(lines)


def format_tournament_check_in(view: TournamentCheckInView) -> str:
    lines = [
        "👥 Участники турнира",
        "",
        format_tournament_label(view.tournament),
        "",
        f"Зарегистрированы заранее: {view.registered_count}",
        f"Пришли: {view.checked_in_count}",
        f"Ещё не отмечены: {view.unchecked_registered_count}",
        f"Без предварительной регистрации: {view.walk_in_count}",
        "",
        "Выберите тип игрока:",
    ]
    return "\n".join(lines)


def format_registered_check_in_confirmation(tournament: TournamentView, user: UserView) -> str:
    return "\n".join(
        [
            f"Добавить {user.display_name} в сегодняшний турнир?",
            "",
            _tournament_type_name(tournament),
            format_date(tournament.date),
        ]
    )


def format_existing_check_in_confirmation(tournament: TournamentView, user: UserView) -> str:
    return "\n".join(
        [
            f"Добавить {user.display_name} в турнир без предварительной регистрации?",
            "",
            _tournament_type_name(tournament),
            format_date(tournament.date),
        ]
    )


def format_new_check_in_confirmation(tournament: TournamentView, display_name: str) -> str:
    return "\n".join(
        [
            f"Создать нового игрока «{display_name}» и добавить в турнир?",
            "",
            _tournament_type_name(tournament),
            format_date(tournament.date),
        ]
    )


def format_check_in_player_notification(tournament: TournamentView) -> str:
    return "\n".join(
        [
            f"✅ Вы прошли check-in на турнир «{_tournament_type_name(tournament)}».",
            format_date(tournament.date),
        ]
    )


def format_tournament_check_in_finished(view: TournamentCheckInView) -> str:
    checked_registered = view.registered_count - view.unchecked_registered_count
    return "\n".join(
        [
            "✅ Состав турнира сохранён",
            "",
            f"Участников: {view.checked_in_count}",
            f"Из предварительных регистраций: {checked_registered}",
            f"Без предварительной регистрации: {view.walk_in_count}",
            f"Не пришли: {view.unchecked_registered_count}",
        ]
    )


def format_admin_result_players(
    results: TournamentResultsView,
    _page: Page,
) -> str:
    lines = [
        texts.admin.ADMIN_RESULTS_PLAYERS_TITLE,
        format_tournament_label(results.tournament),
        "",
        f"Игроки: {results.checked_in_count or len(results.players)}",
        f"В работе: {len(results.players)}",
        "",
    ]
    lines.extend(_admin_result_summary_lines(results))
    return "\n".join(lines)


def format_admin_close_tournament_list(page: Page[TournamentView]) -> str:
    lines = ["Выбери незакрытый турнир:", ""]
    for tournament in page.items:
        lines.append(format_tournament_label(tournament))
    if page.total_pages > 1:
        lines.extend(["", _page_line(page)])
    return "\n".join(lines)


def format_admin_close_tournament_card(results: TournamentResultsView) -> str:
    return "\n".join(
        [
            "🔒 Закрытие турнира",
            "",
            format_date(results.tournament.date),
            _tournament_type_name(results.tournament),
            "",
            f"Игроков: {results.checked_in_count or len(results.players)}",
            "",
            *_admin_result_game_table_lines(results),
            "",
            "Введите Фонд турнира.",
        ]
    )


def format_admin_close_tournament_blocked(errors: list[str]) -> str:
    return "\n".join(
        [
            "Турнир пока нельзя закрыть:",
            "",
            *[f"• {error}" for error in errors],
        ]
    )


def format_admin_tournament_fund_error() -> str:
    return "Фонд турнира должен быть положительным целым числом, кратным 10."


def format_admin_close_tournament_confirmation(
    results: TournamentResultsView,
    tournament_fund: object,
) -> str:
    return "\n".join(
        [
            "Подтвердите закрытие турнира.",
            "",
            format_date(results.tournament.date),
            _tournament_type_name(results.tournament),
            "",
            f"Игроков: {results.checked_in_count or len(results.players)}",
            f"Фонд турнира: {format_decimal(tournament_fund)}",
            "",
            "После подтверждения будут рассчитаны рейтинговые очки,",
            "а турнир станет недоступен для редактирования.",
            "",
            *_admin_result_game_table_lines(results),
        ]
    )


def format_admin_closed_tournament(results: TournamentResultsView) -> str:
    fund = (
        format_decimal(results.tournament_fund)
        if results.tournament_fund is not None
        else "не введен"
    )
    return "\n".join(
        [
            "✅ Турнир закрыт",
            "",
            format_date(results.tournament.date),
            _tournament_type_name(results.tournament),
            "",
            f"Фонд турнира: {fund}",
            f"Игроков: {results.checked_in_count or len(results.players)}",
            "",
            *_admin_result_game_table_lines(results, include_points=True),
        ]
    )


def _admin_result_player_has_value(player: TournamentResultPlayerView) -> bool:
    return (
        player.place is not None
        or player.knockouts_count > 0
        or player.big_knockouts_count > 0
        or player.bonus_points > 0
    )


def _admin_result_summary_lines(results: TournamentResultsView) -> list[str]:
    lines = _admin_result_places_table_lines(results)
    knockout_lines = _admin_result_knockout_lines(results)
    if knockout_lines:
        lines.extend(["", *knockout_lines])
    bonus_lines = _admin_result_bonus_lines(results)
    if bonus_lines:
        lines.extend(["", *bonus_lines])
    return lines


def _admin_result_game_table_lines(
    results: TournamentResultsView,
    *,
    include_points: bool = False,
) -> list[str]:
    rows = []
    sorted_players = sorted(
        results.players,
        key=lambda player: (
            player.place if player.place is not None else 99,
            -player.big_knockouts_count,
            -player.knockouts_count,
            player.display_name.casefold(),
        ),
    )
    if include_points:
        rows.append(f"{'Место':<5}  {'Игрок':<18} {'КО':>3} {'БКО':>4} {'Бонус':>6} {'Очки':>6}")
    else:
        rows.append(f"{'Место':<5}  {'Игрок':<18} {'КО':>3} {'БКО':>4} {'Бонус':>6}")
    for player in sorted_players:
        place = str(player.place) if player.place is not None else "—"
        base = (
            f"{place:<5}  {_code_cell(player.display_name, 18):<18} "
            f"{player.knockouts_count:>3} {player.big_knockouts_count:>4} "
            f"{player.bonus_points:>6}"
        )
        if include_points:
            base += f" {format_decimal(player.total_points):>6}"
        rows.append(base)
    return ["```", *rows, "```"]


def _admin_result_places_table_lines(results: TournamentResultsView) -> list[str]:
    players_by_place = {
        player.place: player
        for player in sorted(results.players, key=lambda player: player.display_name.casefold())
        if player.place is not None
    }
    rows = ["| Место | Игрок", "| ----- | -----"]
    for place in range(1, 6):
        player = players_by_place.get(place)
        display_name = player.display_name if player is not None else "НЕ ВВЕДЕНО"
        rows.append(f"| {place:>5} | {display_name}")
    return ["```", *rows, "```"]


def _admin_result_knockout_lines(results: TournamentResultsView) -> list[str]:
    if results.knockout_mode not in {"small", "small_big"}:
        return []

    players = sorted(
        [
            player
            for player in results.players
            if player.knockouts_count > 0 or player.big_knockouts_count > 0
        ],
        key=_admin_result_player_sort_key,
    )
    if not players:
        return []

    lines = ["🥊:"]
    for player in players:
        result_parts = _admin_result_player_parts(
            knockout_mode=results.knockout_mode,
            knockouts_count=player.knockouts_count,
            big_knockouts_count=player.big_knockouts_count,
            bonus_points=player.bonus_points,
            place=None,
            supports_bonus_points=results.supports_bonus_points,
        )
        lines.append(f"{_markdown_escape(player.display_name)}: {', '.join(result_parts)}")
    return lines


def _admin_result_bonus_lines(results: TournamentResultsView) -> list[str]:
    if not results.supports_bonus_points:
        return []
    players = sorted(
        [player for player in results.players if player.bonus_points > 0],
        key=lambda player: (-player.bonus_points, player.display_name.casefold()),
    )
    if not players:
        return []
    return [
        "Бонус:",
        *[f"{_markdown_escape(player.display_name)}: {player.bonus_points}" for player in players],
    ]


def _markdown_escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("_", "\\_")
        .replace("*", "\\*")
        .replace("`", "\\`")
        .replace("[", "\\[")
    )


def _month_name(month: int) -> str:
    return texts.common.MONTHS[month].capitalize()


def _historical_result_table_lines(
    rows: list[HistoricalTournamentResultRowView],
) -> list[str]:
    lines = [f"{'Место':<5}  {'Игрок':<20} {'🥊':>3} {'👑🥊':>4} {'Очки':>6}"]
    for row in rows:
        place = str(row.place) if row.place is not None else "—"
        lines.append(
            f"{place:<5}  {_code_cell(row.display_name, 20):<20} "
            f"{row.knockouts_count:>3} {row.big_knockouts_count:>4} "
            f"{format_decimal(row.total_points):>6}"
        )
    return lines


def _code_cell(value: str, width: int) -> str:
    compact = " ".join(value.replace("`", "'").split())
    if len(compact) <= width:
        return compact
    return f"{compact[: width - 1]}…"


def _hall_of_fame_line(icon: str, display_name: str | None) -> str:
    if display_name is None:
        return f"{icon} — нет данных"
    return f"{icon} {_markdown_escape(display_name)}"


def _admin_result_player_sort_key(
    player: TournamentResultPlayerView,
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
    bonus_points: int,
    place: int | None,
    supports_bonus_points: bool,
) -> list[str]:
    parts = []
    if place is not None:
        parts.append(_place_label(place))
    if knockout_mode == "small_big":
        if big_knockouts_count > 0:
            parts.append(f"👑🥊 х{big_knockouts_count}")
        if knockouts_count > 0:
            parts.append(f"🥊 х{knockouts_count}")
        if supports_bonus_points and bonus_points > 0:
            parts.append(f"Бонус {bonus_points}")
        return parts
    if knockout_mode == "small":
        if knockouts_count > 0:
            parts.append(f"🥊 х{knockouts_count}")
        if supports_bonus_points and bonus_points > 0:
            parts.append(f"Бонус {bonus_points}")
        return parts
    if supports_bonus_points and bonus_points > 0:
        parts.append(f"Бонус {bonus_points}")
    return parts


def _place_label(place: int) -> str:
    return PLACE_EMOJIS.get(place, str(place))


def format_admin_result_player_detail(
    results: TournamentResultsView,
    player: TournamentResultPlayerView,
) -> str:
    lines = [
        "Результат игрока",
        player.display_name,
    ]
    if results.knockout_mode in {"small", "small_big"}:
        label = "🥊"
        lines.append(f"{label}: {player.knockouts_count}")
    if results.knockout_mode == "small_big":
        lines.append(f"👑🥊: {player.big_knockouts_count}")
    if results.supports_bonus_points:
        lines.append(f"Бонус: {player.bonus_points}")
    if player.place is not None:
        lines.append(f"Место: {_place_label(player.place)}")
    return "\n".join(lines)


def format_admin_result_field_prompt(
    player: TournamentResultPlayerView,
    field_name: str,
) -> str:
    return f"{player.display_name}\n\nВыбери {field_name}:"


def format_season_proposal(proposal: SeasonProposalView) -> str:
    lines = [
        texts.admin.SEASON_PROPOSAL_PREVIEW_TITLE,
        "",
        f"{texts.admin.SEASON_NAME_LABEL}: {proposal.name}",
        f"{texts.admin.SEASON_START_LABEL}: {format_date(proposal.starts_at)}",
    ]
    if proposal.active_season_ends_at is not None:
        lines.extend(
            [
                "",
                f"{texts.admin.SEASON_CURRENT_END_LABEL}: "
                f"{format_numeric_date(proposal.active_season_ends_at)}",
                f"{texts.admin.SEASON_NEW_START_LABEL}: {format_numeric_date(proposal.starts_at)}",
            ]
        )
    return "\n".join(lines)


def format_created_season(season: SeasonView) -> str:
    return "\n".join(
        [
            texts.admin.SEASON_CREATED_TITLE,
            season.name,
            f"{texts.admin.SEASON_START_LABEL}: {format_numeric_date(season.starts_at)}",
            f"{texts.admin.SEASON_SCORING_CONFIG_LABEL}: #{season.scoring_config_id}",
        ]
    )


def format_created_tournaments_prompt(prompt: TournamentPromptView) -> str:
    lines = [texts.admin.TOURNAMENTS_CREATED_TITLE, ""]
    for item in prompt.tournaments:
        lines.append(_format_tournament_prompt_item_label(item))
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


def _format_tournament_prompt_item_label(item: TournamentPromptItemView) -> str:
    tournament = TournamentView(
        id=0,
        tournament_type_id=item.tournament_type.id,
        date=item.date,
        tournament_type_name=item.tournament_type.name,
    )
    return format_tournament_label(tournament)


def _format_public_weekly_schedule_tournament(
    tournament: WeeklyScheduleTournamentView,
) -> str:
    lines = [
        f"🗓 {texts.common.WEEKDAYS[tournament.date.weekday()].upper()} — "
        f"{tournament.tournament_type_name.upper()}",
    ]
    description_lines = _public_tournament_description_lines(tournament)
    if description_lines:
        lines.extend(description_lines)
        lines.append("")
    lines.extend(
        [
            "💰 Условия участия",
            f"Вход: {format_number(tournament.entry_fee)} ₽ — "
            f"{format_number(tournament.entry_stack)} фишек",
        ]
    )
    if len(tournament.rebuys) == 1:
        rebuy = tournament.rebuys[0]
        lines.append(f"Ребай: {format_number(rebuy.fee)} ₽ — {format_number(rebuy.stack)} фишек")
    elif len(tournament.rebuys) > 1:
        lines.extend(
            [
                "",
                "Ребаи:",
                f"{' / '.join(format_number(rebuy.fee) for rebuy in tournament.rebuys)} ₽",
                f"{' / '.join(format_number(rebuy.stack) for rebuy in tournament.rebuys)} фишек",
            ]
        )
    if tournament.addon_fee > 0 and tournament.addon_stack > 0:
        lines.extend(
            [
                "",
                "Аддон:",
                f"{format_number(tournament.addon_fee)} ₽ — "
                f"{format_number(tournament.addon_stack)} фишек",
            ]
        )
    return "\n".join(lines)


def _public_tournament_description_lines(
    tournament: WeeklyScheduleTournamentView,
) -> list[str]:
    lines = list(PUBLIC_TOURNAMENT_DESCRIPTIONS.get(tournament.tournament_type_code, []))
    if not lines and tournament.description:
        lines.append(tournament.description)
    if tournament.tournament_type_code == "freezeout":
        bonus_line = _prize_multiplier_line(tournament)
        if bonus_line is not None:
            lines.append(bonus_line)
    return lines


def _prize_multiplier_line(tournament: WeeklyScheduleTournamentView) -> str | None:
    if tournament.prize_place_multiplier <= 1 or not tournament.prize_place_multiplier_places:
        return None
    try:
        places = " и ".join(
            str(place) for place in json.loads(tournament.prize_place_multiplier_places)
        )
    except (TypeError, ValueError):
        return None
    return f"• Рейтинг за {places} место ×{format_decimal(tournament.prize_place_multiplier)}"


def _split_weekly_schedule_messages(blocks: list[str]) -> list[str]:
    messages: list[str] = []
    current = WEEKLY_SCHEDULE_HEADER
    for block in blocks:
        candidate = (
            f"{current}\n\n{block}"
            if current == WEEKLY_SCHEDULE_HEADER
            else (f"{current}\n\n{WEEKLY_SCHEDULE_SEPARATOR}\n\n{block}")
        )
        if len(candidate) <= TELEGRAM_MESSAGE_LIMIT:
            current = candidate
            continue
        messages.append(current)
        current = block
    if current:
        messages.append(current)
    return messages


def _fallback_tournament_type_name(tournament: TournamentView) -> str:
    return texts.user.TOURNAMENT_TYPE_FALLBACK


def _tournament_type_name(tournament: TournamentView) -> str:
    if tournament.tournament_type_name is not None:
        return tournament.tournament_type_name
    return _fallback_tournament_type_name(tournament)
