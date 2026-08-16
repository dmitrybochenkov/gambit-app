from app.bot.telegram.formatters import common as fmt_common
from app.bot.telegram.formatters import tournaments as tournament_fmt
from app.bot.telegram.texts.admin import results as result_texts

PLACE_EMOJIS = {
    1: "1️⃣",
    2: "2️⃣",
    3: "3️⃣",
    4: "4️⃣",
    5: "5️⃣",
}


def players_table(
    results: object,
    _page: object,
) -> str:
    lines = [
        result_texts.ADMIN_RESULTS_PLAYERS_TITLE,
        tournament_fmt.label(results.tournament),
        "",
        f"Игроки: {len(results.players)}",
        "",
        *_photo_status_lines(results),
        "",
        *_game_table_lines(results, include_required_place_slots=True),
    ]
    return "\n".join(lines)


def management_root(results: object) -> str:
    lines = [
        "🏁 Внести результаты",
        "",
        tournament_fmt.label(results.tournament),
        "",
        *_photo_status_lines(results),
    ]
    return "\n".join(lines)


def photo_menu(results: object) -> str:
    return "\n".join(
        [
            "📸 Фотографии",
            "",
            tournament_fmt.label(results.tournament),
            "",
            f"Фотографий: {results.photo_count}",
        ]
    )


def close_tournament_list(page: object) -> str:
    lines = ["🔒 Закрыть турнир", ""]
    for readiness in page.items:
        lines.append(tournament_fmt.label(readiness.tournament))
        lines.append("✅ Готов к закрытию" if readiness.is_ready else _readiness_warning(readiness))
        lines.append("")
    if lines[-1] == "":
        lines.pop()
    if page.total_pages > 1:
        lines.extend(["", fmt_common.page_line(page)])
    return "\n".join(lines)


def correction_tournament_list(page: object) -> str:
    lines = ["🛠 Корректировать турниры", ""]
    for readiness in page.items:
        lines.append(tournament_fmt.label(readiness.tournament))
        lines.append("✅ Готов к закрытию" if readiness.is_ready else _readiness_warning(readiness))
        lines.append("")
    if lines[-1] == "":
        lines.pop()
    if page.total_pages > 1:
        lines.extend(["", fmt_common.page_line(page)])
    return "\n".join(lines)


def correction_tournament_card(readiness: object) -> str:
    return "\n".join(
        [
            "🛠 Корректировка турнира",
            "",
            tournament_fmt.label(readiness.tournament),
            "",
            "✅ Готов к закрытию" if readiness.is_ready else _readiness_warning(readiness),
        ]
    )


def close_tournament_card(results: object) -> str:
    return "\n".join(
        [
            "🔒 Закрытие турнира",
            "",
            fmt_common.date_long(results.tournament.date),
            tournament_fmt.type_name(results.tournament),
            "",
            f"Игроков: {len(results.players)}",
            f"Фотографий: {results.photo_count}",
            "",
            *_game_table_lines(results, include_points=_show_close_points(results)),
            "",
            "Введите фонд турнира?",
        ]
    )


def tournament_fund_prompt() -> str:
    return "Введите фонд турнира."


def close_tournament_blocked(errors: list[str]) -> str:
    return "\n".join(
        [
            "Турнир пока нельзя закрыть:",
            "",
            *[f"• {error}" for error in errors],
        ]
    )


def _readiness_warning(readiness: object) -> str:
    if not readiness.reasons:
        return "⚠️ Результаты заполнены не полностью."
    reasons = [str(reason).rstrip(".") for reason in readiness.reasons]
    first, *rest = reasons
    normalized = [first, *[reason[:1].lower() + reason[1:] for reason in rest]]
    return f"⚠️ {'; '.join(normalized)}."


def tournament_fund_error() -> str:
    return "Фонд турнира должен быть положительным целым числом, кратным 10."


def tournament_fund_error_prompt() -> str:
    return f"{tournament_fund_error()}\n\n{tournament_fund_prompt()}"


def close_tournament_confirmation(
    results: object,
    tournament_fund: object,
) -> str:
    return "\n".join(
        [
            "Подтвердите закрытие турнира.",
            "",
            fmt_common.date_long(results.tournament.date),
            tournament_fmt.type_name(results.tournament),
            "",
            f"Игроков: {len(results.players)}",
            f"Фонд турнира: {fmt_common.decimal(tournament_fund)}",
            f"Фотографий: {results.photo_count}",
            "",
            "После подтверждения будут рассчитаны рейтинговые очки,",
            "а турнир станет недоступен для редактирования.",
            "",
            *_game_table_lines(results, include_points=_show_close_points(results)),
        ]
    )


def closed_tournament(results: object) -> str:
    fund = (
        fmt_common.decimal(results.tournament_fund)
        if results.tournament_fund is not None
        else "не введен"
    )
    return "\n".join(
        [
            "✅ Турнир закрыт",
            "",
            fmt_common.date_long(results.tournament.date),
            tournament_fmt.type_name(results.tournament),
            "",
            f"Фонд турнира: {fund}",
            f"Игроков: {len(results.players)}",
            "",
            *_game_table_lines(
                results,
                include_points=True,
            ),
        ]
    )


def player_detail(
    results: object,
    player: object,
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
        lines.append(f"{results.bonus_points_label}: {player.bonus_points}")
    if player.place is not None:
        lines.append(f"Место: {_place_label(player.place)}")
    return "\n".join(lines)


def field_prompt(
    player: object,
    field_name: str,
) -> str:
    return f"{player.display_name}\n\nВыбери {field_name}:"


def add_existing_player_prompt(tournament: object, user: object) -> str:
    return "\n".join(
        [
            "Добавить игрока в турнир?",
            "",
            user.display_name,
            tournament_fmt.label(tournament),
        ]
    )


def add_new_player_prompt(tournament: object, display_name: str) -> str:
    return "\n".join(
        [
            f"Создать нового игрока «{display_name}» и добавить в турнир?",
            "",
            tournament_fmt.label(tournament),
        ]
    )


def photo_upload_prompt(photo_count: int, *, limit_reached: bool = False) -> str:
    lines = [
        "📸 Добавление фото",
        "",
        "Пришли фотографии турнира.",
        "Можно отправлять по одной или альбомом.",
        "",
        f"Загружено фото: {photo_count}",
    ]
    if limit_reached:
        lines.extend(["⚠️ Можно добавить не больше 10 фотографий."])
    lines.extend(
        [
            "",
            "Когда закончишь — нажми «Готово».",
        ]
    )
    return "\n".join(lines)


def delete_photos_confirmation() -> str:
    return "Удалить все фотографии турнира?"


def player_has_value(player: object) -> bool:
    return (
        player.place is not None
        or player.knockouts_count > 0
        or player.big_knockouts_count > 0
        or player.bonus_points > 0
    )


def summary_lines(results: object) -> list[str]:
    lines = _places_table_lines(results)
    knockout_lines = _knockout_lines(results)
    if knockout_lines:
        lines.extend(["", *knockout_lines])
    bonus_lines = _bonus_lines(results)
    if bonus_lines:
        lines.extend(["", *bonus_lines])
    return lines


def player_parts(
    *,
    knockout_mode: str,
    knockouts_count: int,
    big_knockouts_count: int,
    bonus_points: int,
    place: int | None,
    supports_bonus_points: bool,
    bonus_points_label: str = "Бонус",
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
            parts.append(f"{bonus_points_label} {bonus_points}")
        return parts
    if knockout_mode == "small":
        if knockouts_count > 0:
            parts.append(f"🥊 х{knockouts_count}")
        if supports_bonus_points and bonus_points > 0:
            parts.append(f"{bonus_points_label} {bonus_points}")
        return parts
    if supports_bonus_points and bonus_points > 0:
        parts.append(f"{bonus_points_label} {bonus_points}")
    return parts


def place_label(place: int) -> str:
    return _place_label(place)


def _game_table_lines(
    results: object,
    *,
    include_points: bool = False,
    force_all_columns: bool = False,
    include_required_place_slots: bool = False,
) -> list[str]:
    rows = []
    sorted_players = sorted(
        _table_players(results, include_required_place_slots=include_required_place_slots),
        key=lambda player: (
            player.place if player.place is not None else 99,
            -player.big_knockouts_count,
            -player.knockouts_count,
            player.display_name.casefold(),
        ),
    )
    show_knockouts = force_all_columns or results.knockout_mode in {"small", "small_big"}
    show_big_knockouts = force_all_columns or results.knockout_mode == "small_big"
    show_bonus = force_all_columns or results.supports_bonus_points
    header = f"{'Место':<5}  {'Игрок':<18}"
    if show_knockouts:
        header += f" {'КО':>3}"
    if show_big_knockouts:
        header += f" {'БКО':>4}"
    if show_bonus:
        header += f" {results.bonus_points_label:>9}"
    if include_points:
        header += f" {'Очки':>6}"
    rows.append(header)
    for player in sorted_players:
        place = str(player.place) if player.place is not None else "—"
        base = f"{place:<5}  {fmt_common.code_cell(player.display_name, 18):<18}"
        if show_knockouts:
            base += _table_number_cell(player, player.knockouts_count, width=3)
        if show_big_knockouts:
            base += _table_number_cell(player, player.big_knockouts_count, width=4)
        if show_bonus:
            base += _table_number_cell(player, player.bonus_points, width=9)
        if include_points:
            value = "" if _is_missing_place_row(player) else fmt_common.points(player.total_points)
            base += f" {value:>6}"
        rows.append(base)
    return ["```", *rows, "```"]


def _show_close_points(results: object) -> bool:
    return getattr(results.tournament, "tournament_type_code", None) == "mystery_bounty"


def _photo_status_lines(results: object) -> list[str]:
    if results.photo_count <= 0:
        return [
            "⚠️ Фото турнира не добавлены.",
            "Без фото турнир нельзя закрыть.",
        ]
    return [f"📸 Фотографий: {results.photo_count}"]


def _table_number_cell(player: object, value: int, *, width: int) -> str:
    if _is_missing_place_row(player):
        return f" {'':>{width}}"
    return f" {value:>{width}}"


def _is_missing_place_row(player: object) -> bool:
    return bool(getattr(player, "is_missing_place", False))


def _table_players(
    results: object,
    *,
    include_required_place_slots: bool,
) -> list[object]:
    if not include_required_place_slots:
        return results.entered_players

    players_by_place = {
        player.place: player for player in results.entered_players if player.place is not None
    }
    rows: list[object] = []
    for place in results.required_places:
        player = players_by_place.get(place)
        rows.append(player if player is not None else _MissingPlaceRow(place=place))
    rows.extend(player for player in results.entered_players if player.place is None)
    return rows


def _places_table_lines(results: object) -> list[str]:
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


def _knockout_lines(results: object) -> list[str]:
    if results.knockout_mode not in {"small", "small_big"}:
        return []

    players = sorted(
        [
            player
            for player in results.players
            if player.knockouts_count > 0 or player.big_knockouts_count > 0
        ],
        key=_player_sort_key,
    )
    if not players:
        return []

    lines = ["🥊:"]
    for player in players:
        result_parts = player_parts(
            knockout_mode=results.knockout_mode,
            knockouts_count=player.knockouts_count,
            big_knockouts_count=player.big_knockouts_count,
            bonus_points=player.bonus_points,
            place=None,
            supports_bonus_points=results.supports_bonus_points,
            bonus_points_label=results.bonus_points_label,
        )
        lines.append(
            f"{fmt_common.markdown_escape(player.display_name)}: {', '.join(result_parts)}"
        )
    return lines


def _bonus_lines(results: object) -> list[str]:
    if not results.supports_bonus_points:
        return []
    players = sorted(
        [player for player in results.players if player.bonus_points > 0],
        key=lambda player: (-player.bonus_points, player.display_name.casefold()),
    )
    if not players:
        return []
    return [
        f"{results.bonus_points_label}:",
        *[
            f"{fmt_common.markdown_escape(player.display_name)}: {player.bonus_points}"
            for player in players
        ],
    ]


def _player_sort_key(
    player: object,
) -> tuple[int, int, int, str]:
    return (
        -player.big_knockouts_count,
        -player.knockouts_count,
        player.place if player.place is not None else 99,
        player.display_name.casefold(),
    )


def _place_label(place: int) -> str:
    return PLACE_EMOJIS.get(place, str(place))


class _MissingPlaceRow:
    is_missing_place = True
    display_name = "НЕ ВВЕДЕНО"
    knockouts_count = 0
    big_knockouts_count = 0
    bonus_points = 0
    total_points = 0

    def __init__(self, place: int) -> None:
        self.place = place
