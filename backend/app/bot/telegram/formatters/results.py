from app.bot.telegram.formatters import common as fmt_common
from app.bot.telegram.formatters import publications as publication_fmt
from app.bot.telegram.formatters import tournaments as tournament_fmt
from app.bot.telegram.texts.admin import results as result_texts

PLACE_EMOJIS = {
    1: "1️⃣",
    2: "2️⃣",
    3: "3️⃣",
    4: "4️⃣",
    5: "5️⃣",
}

MAX_TABLE_WIDTH = 35
MAX_PLAYER_NAME_WIDTH = 21
_PLACE_WIDTH = 1
_KNOCKOUT_WIDTH = 2
_BIG_KNOCKOUT_WIDTH = 3
_BONUS_WIDTH = 5
_POINTS_WIDTH = 4


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


def tournament_list(page: object) -> str:
    lines = ["Выбери турнир:", ""]
    for tournament in page.items:
        lines.append(f"{tournament.id} — {tournament_fmt.label(tournament)}")
    if page.total_pages > 1:
        lines.extend(["", fmt_common.page_line(page)])
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


def combinations_root(view: object) -> str:
    lines = ["🃏 Комбинации вечера", ""]
    lines.extend(
        f"{combination.display_name} — "
        f"{publication_fmt.combination_label(combination.combination_type, rank=combination.rank)}"
        for combination in view.combinations
    )
    if lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def combination_player_prompt(view: object) -> str:
    return "\n".join(["🃏 Комбинации вечера", "", "Выбери игрока:"])


def combination_type_prompt(player_name: str) -> str:
    return "\n".join(["🃏 Комбинации вечера", "", player_name, "", "Выбери комбинацию:"])


def four_of_a_kind_rank_prompt(player_name: str) -> str:
    return "\n".join(
        [
            "🃏 Комбинации вечера",
            "",
            player_name,
            "",
            "Выбери достоинство каре:",
        ]
    )


def combination_delete_prompt(view: object) -> str:
    return "\n".join(["🃏 Комбинации вечера", "", "Что удалить?"])


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


def closed_correction_tournament_list(page: object) -> str:
    lines = ["🔒 Закрытые турниры", ""]
    if not page.items:
        lines.append("Закрытых турниров нет.")
    else:
        for tournament in page.items:
            lines.append(tournament_fmt.label(tournament))
    if page.total_pages > 1:
        lines.extend(["", fmt_common.page_line(page)])
    return "\n".join(lines)


def closed_correction_tournament_card(results: object) -> str:
    return "\n".join(
        [
            "🔒 Закрытый турнир",
            "",
            tournament_fmt.label(results.tournament),
            "",
            f"Игроков: {len(results.players)}",
            f"Фонд: {_fund_label(results.tournament_fund)}",
            "Статус: 🔒 Закрыт",
        ]
    )


def closed_correction_players(results: object) -> str:
    lines = [
        "👥 Игроки",
        "",
        tournament_fmt.label(results.tournament),
        "",
    ]
    if not results.players:
        lines.append("Игроков пока нет.")
    else:
        lines.extend(player.display_name for player in results.players)
    return "\n".join(lines)


def closed_add_player_search_prompt(results: object) -> str:
    return "\n".join(
        [
            "Добавить игрока",
            "",
            tournament_fmt.label(results.tournament),
            "",
            "Введи имя игрока из базы.",
        ]
    )


def closed_add_player_confirmation(results: object, user: object) -> str:
    return "\n".join(
        [
            "Добавить игрока в закрытый турнир?",
            "",
            user.display_name,
            tournament_fmt.label(results.tournament),
        ]
    )


def closed_delete_player_confirmation(results: object, player: object) -> str:
    lines = [
        "Удалить игрока из турнира?",
        "",
        tournament_fmt.label(results.tournament),
        f"Игрок: {player.display_name}",
        "",
        f"Место: {_place_label(player.place) if player.place is not None else '—'}",
    ]
    if results.knockout_mode in {"small", "small_big"}:
        lines.append(f"KO: {player.knockouts_count}")
    if results.knockout_mode == "small_big":
        lines.append(f"BKO: {player.big_knockouts_count}")
    if results.supports_bonus_points:
        lines.append(f"{results.bonus_points_label}: {player.bonus_points}")
    lines.extend(
        [
            "",
            "Будет удалено участие только в этом турнире.",
            "Игрок останется в базе.",
        ]
    )
    return "\n".join(lines)


def closed_fund_card(results: object) -> str:
    return "\n".join(
        [
            "💰 Фонд турнира",
            "",
            tournament_fmt.label(results.tournament),
            "",
            f"Текущий фонд: {_fund_label(results.tournament_fund)}",
        ]
    )


def closed_fund_prompt(results: object) -> str:
    return "\n".join(
        [
            "Введите новый фонд турнира.",
            "",
            tournament_fmt.label(results.tournament),
            f"Сейчас: {_fund_label(results.tournament_fund)}",
        ]
    )


def closed_correction_summary(result: object) -> str:
    fund_changed = result.fund_before != result.fund_after
    if not result.result_changes and not fund_changed:
        return "Изменений нет."
    lines = [
        "Проверь исправления перед применением.",
        "",
        "Что изменилось:",
    ]
    if fund_changed:
        lines.append(f"Фонд: {_fund_label(result.fund_before)} → {_fund_label(result.fund_after)}")
    for player in result.result_changes:
        lines.append(player.display_name)
        lines.extend(f"{field.label}: {field.before} → {field.after}" for field in player.fields)
        lines.append("")
    if result.before_results is not None and result.after_results is not None:
        if lines[-1] != "":
            lines.append("")
        lines.extend(
            [
                "БЫЛО",
                *_game_table_lines(result.before_results, include_all_players=True),
                "",
                "СТАЛО",
                *_game_table_lines(result.after_results, include_all_players=True),
                "",
            ]
        )
    if result.reward_changes:
        lines.append("Бонусы:")
        for reward in result.reward_changes:
            lines.append(_reward_change_line(reward))
        lines.append("")
    if result.used_reward_warnings:
        lines.append("⚠️ Обрати внимание:")
        lines.extend(_used_reward_warning(reward) for reward in result.used_reward_warnings)
    if lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def _fund_label(value: int | None) -> str:
    if value is None:
        return "—"
    return fmt_common.decimal(value)


def _reward_change_line(reward: object) -> str:
    before = _chips(reward.old_chips_amount)
    after = _chips(reward.new_chips_amount)
    return f"{reward.display_name}: {before} → {after}"


def _used_reward_warning(reward: object) -> str:
    return f"бонус {_chips(reward.old_chips_amount)} {reward.display_name} уже был использован."


def _chips(value: int | None) -> str:
    if value is None:
        return "—"
    return f"+{fmt_common.number(value)}"


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
            *_game_table_lines(results),
            "",
            "Введите фонд турнира?",
        ]
    )


def tournament_fund_prompt(tournament: object | None = None) -> str:
    if tournament is None:
        return "Введите фонд турнира."

    tournament_name = tournament.tournament_type_name or "Неопределённый турнир"
    return (
        f"Введите фонд турнира для "
        f"{tournament.date.day:02d}.{tournament.date.month:02d} — {tournament_name}"
    )


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


def close_tournament_preview_confirmation(results: object) -> str:
    return "\n".join(
        [
            "Выше — сообщение для игроков. Ниже — результаты, которые пойдут в базу. Всё верно?",
            "",
            *_game_table_lines(
                results,
                include_all_players=True,
            ),
        ]
    )


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
            *_game_table_lines(results),
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
        f"Игрок: {player.display_name}",
        "",
        f"Место: {_place_label(player.place) if player.place is not None else '—'}",
    ]
    if results.knockout_mode in {"small", "small_big"}:
        label = "🥊"
        lines.append(f"{label}: {player.knockouts_count}")
    if results.knockout_mode == "small_big":
        lines.append(f"👑🥊: {player.big_knockouts_count}")
    if results.supports_bonus_points:
        lines.append(f"{results.bonus_points_label}: {player.bonus_points}")
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


def replace_result_player_prompt(tournament: object, current_player: object, user: object) -> str:
    return "\n".join(
        [
            "Заменить игрока в результате?",
            "",
            f"{current_player.display_name} → {user.display_name}",
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
    include_all_players: bool = False,
) -> list[str]:
    rows = []
    table_players = (
        results.players
        if include_all_players
        else _table_players(
            results,
            include_required_place_slots=include_required_place_slots,
        )
    )

    sorted_players = sorted(
        table_players,
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
    columns = _game_table_columns(
        show_knockouts=show_knockouts,
        show_big_knockouts=show_big_knockouts,
        show_bonus=show_bonus,
        include_points=include_points,
    )
    name_width = _game_table_name_width(sorted_players, columns)
    header = " ".join(["№", f"{'Игрок':<{name_width}}", *[column[0] for column in columns]])
    rows.append(header.rstrip())
    for player in sorted_players:
        place = str(player.place) if player.place is not None else "—"
        cells = [
            f"{place:>{_PLACE_WIDTH}}",
            f"{fmt_common.code_cell(player.display_name, name_width):<{name_width}}",
        ]
        if show_knockouts:
            cells.append(_table_number_cell(player, player.knockouts_count, width=_KNOCKOUT_WIDTH))
        if show_big_knockouts:
            cells.append(
                _table_number_cell(player, player.big_knockouts_count, width=_BIG_KNOCKOUT_WIDTH)
            )
        if show_bonus:
            cells.append(_table_number_cell(player, player.bonus_points, width=_BONUS_WIDTH))
        if include_points:
            value = "" if _is_missing_place_row(player) else fmt_common.points(player.total_points)
            cells.append(f"{value:>{_POINTS_WIDTH}}")
        rows.append(" ".join(cells).rstrip())
    return ["```", *rows, "```"]


def _game_table_columns(
    *,
    show_knockouts: bool,
    show_big_knockouts: bool,
    show_bonus: bool,
    include_points: bool,
) -> list[tuple[str, int]]:
    columns: list[tuple[str, int]] = []
    if show_knockouts:
        columns.append((f"{'КО':>{_KNOCKOUT_WIDTH}}", _KNOCKOUT_WIDTH))
    if show_big_knockouts:
        columns.append((f"{'БКО':>{_BIG_KNOCKOUT_WIDTH}}", _BIG_KNOCKOUT_WIDTH))
    if show_bonus:
        columns.append((f"{'Бонус':>{_BONUS_WIDTH}}", _BONUS_WIDTH))
    if include_points:
        columns.append((f"{'Очки':>{_POINTS_WIDTH}}", _POINTS_WIDTH))
    return columns


def _game_table_name_width(rows: list[object], columns: list[tuple[str, int]]) -> int:
    separators_width = 1 + len(columns)
    technical_width = _PLACE_WIDTH + separators_width + sum(width for _label, width in columns)
    available_width = MAX_TABLE_WIDTH - technical_width
    longest_name = max([len("Игрок"), *[len(str(row.display_name)) for row in rows]])
    return min(longest_name, MAX_PLAYER_NAME_WIDTH, available_width)


def _photo_status_lines(results: object) -> list[str]:
    if results.photo_count <= 0:
        return [
            "⚠️ Фото турнира не добавлены.",
            "Без фото турнир нельзя закрыть.",
        ]
    return [f"📸 Фотографий: {results.photo_count}"]


def _table_number_cell(player: object, value: int, *, width: int) -> str:
    if _is_missing_place_row(player):
        return f"{'':>{width}}"
    return f"{value:>{width}}"


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
