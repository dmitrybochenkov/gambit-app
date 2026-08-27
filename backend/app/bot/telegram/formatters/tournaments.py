from app.bot.telegram.formatters import common as fmt_common
from app.bot.telegram.texts import common as common_texts
from app.bot.telegram.texts.superadmin import tournaments as superadmin_tournament_texts
from app.bot.telegram.texts.user import tournaments as tournament_texts
from app.domain.prize_multiplier_places import (
    PrizeMultiplierPlacesError,
    parse_prize_multiplier_places,
)

CALENDAR_TYPE_ABBREVIATIONS = {
    "bounty": "B",
    "classic": "C",
    "freezeout": "F",
    "double_double": "DD",
    "mystery_bounty": "MB",
    "boss_bounty": "BB",
    "legacy_unknown": "?",
}
_MONTH_CELL_WIDTH = 4


def label(tournament: object) -> str:
    weekday = common_texts.WEEKDAYS[tournament.date.weekday()]
    month = common_texts.MONTHS[tournament.date.month]
    return f"{weekday}, {tournament.date.day} {month} — {type_name(tournament)}"


def schedule(tournaments: list) -> str:
    return schedule_root(tournaments)


def schedule_root(tournaments: list) -> str:
    if not tournaments:
        return "\n\n".join(
            [
                tournament_texts.TOURNAMENT_SCHEDULE_TITLE,
                tournament_texts.TOURNAMENTS_EMPTY,
            ]
        )

    return "\n\n".join(
        [
            tournament_texts.TOURNAMENT_SCHEDULE_TITLE,
            tournament_texts.TOURNAMENT_SCHEDULE_INSTRUCTION,
        ]
    )


def schedule_detail(details: object) -> str:
    lines = [
        f"🗓 {label(details)}",
    ]
    if details.description:
        lines.extend(["", str(details.description)])
    if details.economy is not None:
        lines.extend(["", *_economy_lines(details.economy)])
    rule_lines = _rule_lines(details.rules)
    if rule_lines:
        lines.extend(["", *rule_lines])
    return "\n".join(lines)


def superadmin_open_list(page: object) -> str:
    if not page.items:
        return "\n\n".join(
            [
                superadmin_tournament_texts.OPEN_TOURNAMENTS_TITLE,
                superadmin_tournament_texts.OPEN_TOURNAMENTS_EMPTY,
            ]
        )
    lines = [superadmin_tournament_texts.OPEN_TOURNAMENTS_TITLE]
    if page.total_pages > 1:
        lines.extend(["", fmt_common.page_line(page)])
    return "\n".join(lines)


def superadmin_open_card(readiness: object) -> str:
    lines = [
        label(readiness.tournament),
        "",
        f"Игроков: {readiness.players_count}",
        "",
        "Статус готовности к закрытию:",
    ]
    if readiness.is_ready:
        lines.append("готов")
    else:
        lines.extend(_readiness_reasons(readiness))
    lines.extend(["", superadmin_tournament_texts.OPEN_TOURNAMENT_EDITING_INFO])
    return "\n".join(lines)


def superadmin_open_player_list(page: object, tournament: object) -> str:
    if not page.items:
        return "\n\n".join(
            [
                "🗑 Удалить игрока",
                label(tournament),
                superadmin_tournament_texts.OPEN_TOURNAMENT_PLAYERS_EMPTY,
            ]
        )
    lines = ["🗑 Удалить игрока", "", label(tournament)]
    if page.total_pages > 1:
        lines.extend(["", fmt_common.page_line(page)])
    return "\n".join(lines)


def superadmin_open_delete_confirmation(preview: object) -> str:
    lines = [
        "Удалить игрока из турнира?",
        "",
        label(preview.tournament),
        f"Игрок: {preview.player.display_name}",
    ]
    details = _delete_player_details(preview)
    if details:
        lines.extend(["", *details])
    lines.extend(["", superadmin_tournament_texts.OPEN_TOURNAMENT_DELETE_WARNING])
    return "\n".join(lines)


def superadmin_calendar_month(view: object) -> str:
    month_name = common_texts.MONTHS[view.month].upper()
    title = f"{month_name} {view.year}".center(43)
    lines = [
        "📅 Календарь",
        "",
        "```",
        title.rstrip(),
        "",
        "     Пн   Вт   Ср   Чт   Пт   Сб   Вс",
    ]
    for week in view.weeks:
        date_cells = [
            f"{day.date.day:02d}".center(_MONTH_CELL_WIDTH) if day.in_month else " " * 4
            for day in week.days
        ]
        type_cells = [
            _calendar_day_code(day).center(_MONTH_CELL_WIDTH) if day.in_month else " " * 4
            for day in week.days
        ]
        lines.append(f"{week.row_number:<2} " + " ".join(date_cells).rstrip())
        if any(cell.strip() for cell in type_cells):
            lines.append("   " + " ".join(type_cells).rstrip())
        lines.append("")
    if lines[-1] == "":
        lines.pop()
    lines.extend(
        [
            "```",
            "",
            "B — Bounty",
            "C — Classic",
            "F — Freezeout",
            "DD — Double Double",
            "MB — Mystery Bounty",
            "BB — Boss Bounty",
            "? — тип не определён",
        ]
    )
    return "\n".join(lines)


def superadmin_calendar_week(view: object) -> str:
    lines = [
        f"📅 {view.week_start.day}–{view.week_end.day} {common_texts.MONTHS[view.week_end.month]}",
        "",
        "Выбери дату:",
    ]
    if view.is_empty:
        lines.extend(["", superadmin_tournament_texts.CALENDAR_EMPTY_WEEK_HINT])
    return "\n".join(lines)


def superadmin_calendar_create_preview(view: object) -> str:
    return "\n".join(
        [
            "➕ Создать турнир?",
            "",
            f"{_date_with_weekday(view.tournament_date)}",
            view.tournament_type.name,
            "",
            "Регистрация будет закрыта до утверждения расписания.",
        ]
    )


def superadmin_calendar_autofill_preview(view: object) -> str:
    lines = [
        f"✨ Расписание на {view.week_start.day}–{view.week_end.day} "
        f"{common_texts.MONTHS[view.week_end.month]}",
        "",
    ]
    lines.extend(
        f"{_date_with_weekday(item.tournament_date)} — {item.tournament_type.name}"
        for item in view.tournaments
    )
    lines.extend(["", "Создать эти турниры?"])
    return "\n".join(lines)


def superadmin_calendar_approval_preview(view: object) -> str:
    lines = [
        "✅ Утвердить неделю?",
        "",
        "Регистрация откроется для турниров:",
        "",
    ]
    lines.extend(label(tournament) for tournament in view.tournaments)
    return "\n".join(lines)


def superadmin_calendar_tournament_card(day: object) -> str:
    tournament = day.tournament
    if tournament is None:
        return "Турнир не найден."
    return "\n".join(
        [
            f"{_date_with_weekday(tournament.date)}",
            type_name(tournament),
            "",
            f"Зарегистрировано: {day.registrations_count}",
            f"Регистрация: {'открыта' if tournament.registration_open else 'закрыта'}",
        ]
    )


def superadmin_calendar_type_change_preview(view: object) -> str:
    return "\n".join(
        [
            "Изменить тип турнира?",
            "",
            f"{view.tournament.date.day:02d}.{view.tournament.date.month:02d}",
            f"{type_name(view.tournament)} → {view.new_type.name}",
        ]
    )


def superadmin_calendar_delete_preview(view: object) -> str:
    return "\n".join(
        [
            "🗑 Удалить турнир?",
            "",
            label(view.tournament),
            "",
            f"Зарегистрировано: {view.registrations_count}",
            "",
            "Турнир и регистрации на него будут удалены.",
            "Зарегистрированные игроки получат уведомление об отмене.",
        ]
    )


def type_name(tournament: object) -> str:
    if tournament.tournament_type_name is not None:
        return tournament.tournament_type_name
    return tournament_texts.TOURNAMENT_TYPE_FALLBACK


def short_label(tournament: object) -> str:
    return f"{tournament.date.day:02d}.{tournament.date.month:02d} — {type_name(tournament)}"


def _calendar_day_code(day: object) -> str:
    if day.tournament is None:
        return ""
    return CALENDAR_TYPE_ABBREVIATIONS.get(day.tournament.tournament_type_code, "?")


def _date_with_weekday(value: object) -> str:
    weekday = common_texts.WEEKDAYS[value.weekday()].lower()
    return f"{value.day:02d}.{value.month:02d}.{value.year}, {weekday}"


def _readiness_reasons(readiness: object) -> list[str]:
    if not readiness.reasons:
        return ["Результаты заполнены не полностью."]
    return [f"• {reason}" for reason in readiness.reasons]


def _delete_player_details(preview: object) -> list[str]:
    player = preview.player
    lines: list[str] = []
    if player.place is not None:
        lines.append(f"Место: {player.place}")
    if player.knockouts_count:
        lines.append(f"KO: {player.knockouts_count}")
    if player.big_knockouts_count:
        lines.append(f"BKO: {player.big_knockouts_count}")
    if player.bonus_points:
        lines.append(f"Бонус: {player.bonus_points}")
    if preview.combinations_count:
        lines.append(f"Комбинации: {preview.combinations_count}")
    return lines


def _economy_lines(economy: object) -> list[str]:
    lines = [
        "💰 Условия участия",
        f"Вход: {fmt_common.number(economy.entry_fee)} ₽ — "
        f"{fmt_common.number(economy.entry_stack)} фишек",
    ]
    if len(economy.rebuys) == 1:
        rebuy = economy.rebuys[0]
        lines.append(
            f"Ребай: {fmt_common.number(rebuy.fee)} ₽ — {fmt_common.number(rebuy.stack)} фишек"
        )
    elif len(economy.rebuys) > 1:
        lines.extend(
            [
                "",
                "Ребаи:",
                f"{' / '.join(fmt_common.number(rebuy.fee) for rebuy in economy.rebuys)} ₽",
                f"{' / '.join(fmt_common.number(rebuy.stack) for rebuy in economy.rebuys)} фишек",
            ]
        )
    if economy.addon_fee > 0 and economy.addon_stack > 0:
        lines.extend(
            [
                "",
                "Аддон:",
                f"{fmt_common.number(economy.addon_fee)} ₽ — "
                f"{fmt_common.number(economy.addon_stack)} фишек",
            ]
        )
    return lines


def _rule_lines(rules: object | None) -> list[str]:
    if rules is None:
        return []
    lines = ["📌 Правила"]
    if rules.points_multiplier != 1:
        lines.append(f"Множитель рейтинга: ×{fmt_common.decimal(rules.points_multiplier)}")
    if rules.prize_place_multiplier != 1:
        places = _prize_places_label(rules.prize_place_multiplier_places)
        suffix = f" ({places})" if places else ""
        lines.append(
            f"Множитель призовых мест: ×{fmt_common.decimal(rules.prize_place_multiplier)}{suffix}"
        )
    if rules.knockout_mode != "none":
        lines.append(f"Нокауты: {_knockout_mode_label(rules.knockout_mode)}")
    if rules.supports_bonus_points:
        lines.append("Бонусные очки")
    return lines if len(lines) > 1 else []


def _prize_places_label(raw_places: str | None) -> str | None:
    if not raw_places:
        return None
    try:
        places = parse_prize_multiplier_places(raw_places)
    except PrizeMultiplierPlacesError:
        return None
    return ", ".join(str(place) for place in places)


def _knockout_mode_label(knockout_mode: str) -> str:
    if knockout_mode == "small":
        return "КО"
    if knockout_mode == "small_big":
        return "КО и БКО"
    return knockout_mode
