from collections.abc import Iterable
from datetime import date
from html import escape

from app.bot.telegram.formatters import common as fmt_common
from app.bot.telegram.texts import common as common_texts
from app.bot.telegram.texts.superadmin import tournaments as superadmin_tournament_texts
from app.bot.telegram.texts.user import tournaments as tournament_texts
from app.domain.prize_multiplier_places import (
    PrizeMultiplierPlacesError,
    parse_prize_multiplier_places,
)

_MONTH_CELL_WIDTH = 4
CALENDAR_MONTHS_NOMINATIVE = {
    1: "ЯНВАРЬ",
    2: "ФЕВРАЛЬ",
    3: "МАРТ",
    4: "АПРЕЛЬ",
    5: "МАЙ",
    6: "ИЮНЬ",
    7: "ИЮЛЬ",
    8: "АВГУСТ",
    9: "СЕНТЯБРЬ",
    10: "ОКТЯБРЬ",
    11: "НОЯБРЬ",
    12: "ДЕКАБРЬ",
}
WEEKDAY_SHORT_NAMES = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")
WEEKDAY_NAMES = (
    "Понедельник",
    "Вторник",
    "Среда",
    "Четверг",
    "Пятница",
    "Суббота",
    "Воскресенье",
)


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
    weekday = common_texts.WEEKDAYS[details.date.weekday()]
    month = common_texts.MONTHS[details.date.month]
    return public_tournament_card(
        name=details.tournament_type_name,
        description=details.description,
        economy=details.economy,
        date_label=f"{weekday}, {details.date.day} {month}",
    )


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
    month_name = CALENDAR_MONTHS_NOMINATIVE[view.month]
    title = f"{month_name} {view.year}".center(43)
    lines = [
        "📅 Календарь",
        "",
        "```",
        title.rstrip(),
        "",
        _calendar_month_row("", WEEKDAY_SHORT_NAMES),
    ]
    for week in view.weeks:
        date_cells = [f"{day.date.day:02d}" if day.in_month else "" for day in week.days]
        type_cells = [_calendar_day_code(day) if day.in_month else "" for day in week.days]
        lines.append(_calendar_month_row(str(week.row_number), date_cells))
        if any(cell.strip() for cell in type_cells):
            lines.append(_calendar_month_row("", type_cells))
        lines.append("")
    if lines[-1] == "":
        lines.pop()
    lines.append("```")
    legend = _calendar_legend(view)
    if legend:
        lines.extend(["", *legend])
    return "\n".join(lines)


def _calendar_month_row(week_label: str, cells: Iterable[object]) -> str:
    prefix = f"{week_label:<2} "
    return prefix + " ".join(str(cell).center(_MONTH_CELL_WIDTH) for cell in cells).rstrip()


def superadmin_calendar_format_detail(view: object) -> str:
    return _admin_tournament_card(view, show_creatable_status=True)


def superadmin_calendar_week(view: object) -> str:
    lines = [
        f"📅 {_calendar_week_range(view.week_start, view.week_end)}",
        "",
        "Выбери дату:",
    ]
    if view.is_empty:
        lines.extend(["", superadmin_tournament_texts.CALENDAR_EMPTY_WEEK_HINT])
    return "\n".join(lines)


def superadmin_calendar_empty_day(tournament_date: date) -> str:
    return f"📅 {_date_with_weekday(tournament_date)}\n\nНа этот день турнир не назначен."


def weekly_template_summary(draft: dict[int, list[object]]) -> str:
    lines = ["⚙️ Шаблон расписания", ""]
    for weekday, label in enumerate(WEEKDAY_SHORT_NAMES):
        items = draft.get(weekday, [])
        if not items:
            value = "не задан"
        elif len(items) == 1:
            value = items[0].calendar_code
        else:
            value = "🔄 " + " → ".join(item.calendar_code for item in items)
        lines.append(f"{label} — {value}")
    return "\n".join(lines)


def weekly_template_day(weekday: int, items: list[object]) -> str:
    lines = [f"⚙️ {WEEKDAY_NAMES[weekday]}", ""]
    if not items:
        lines.append("Формат не задан.")
    elif len(items) == 1:
        lines.append(f"Формат:\n{items[0].calendar_code} — {items[0].name}")
    else:
        lines.append("Ротация:")
        lines.extend(
            f"{index}. {item.calendar_code} — {item.name}"
            for index, item in enumerate(items, start=1)
        )
    return "\n".join(lines)


def weekly_template_item(item: object) -> str:
    return f"⚙️ Формат\n\n{item.calendar_code} — {item.name}"


def weekly_autofill_summary(
    *, week_start: date, week_end: date, draft: dict[date, object | None]
) -> str:
    lines = [f"✏️ Расписание на {_calendar_week_range(week_start, week_end)}", ""]
    for tournament_date, tournament_type in draft.items():
        value = "—" if tournament_type is None else tournament_type.calendar_code
        lines.append(f"{WEEKDAY_SHORT_NAMES[tournament_date.weekday()]} — {value}")
    return "\n".join(lines)


def weekly_autofill_day(tournament_date: date, tournament_type: object | None) -> str:
    lines = [f"📅 {_date_with_weekday(tournament_date)}", ""]
    if tournament_type is None:
        lines.append("Турнир не запланирован.")
    else:
        lines.append(f"Сейчас: {tournament_type.calendar_code} — {tournament_type.name}")
    return "\n".join(lines)


def tournament_format_list() -> str:
    return "🏆 Форматы турниров\n\nВыберите формат:"


def tournament_format_detail(tournament_format: object) -> str:
    return _admin_tournament_card(tournament_format, show_creatable_status=True)


def tournament_format_disable_confirmation(
    tournament_format: object,
    affected_weekdays: tuple[int, ...],
) -> str:
    lines = [f"⚠️ Отключить {tournament_format.calendar_code}?"]
    if affected_weekdays:
        lines.extend(
            [
                "",
                f"{tournament_format.calendar_code} используется в шаблоне расписания:",
                *(f"• {WEEKDAY_SHORT_NAMES[weekday]}" for weekday in affected_weekdays),
                "",
                "При отключении формат будет удалён из шаблона.",
            ]
        )
    return "\n".join(lines)


def _calendar_week_range(week_start: date, week_end: date) -> str:
    if week_start.month == week_end.month and week_start.year == week_end.year:
        return f"{week_start.day}–{week_end.day} {common_texts.MONTHS[week_end.month]}"
    return (
        f"{week_start.day} {common_texts.MONTHS[week_start.month]} — "
        f"{week_end.day} {common_texts.MONTHS[week_end.month]}"
    )


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


def superadmin_calendar_tournament_card(detail: object, registrations_count: int) -> str:
    weekday = common_texts.WEEKDAYS[detail.tournament.date.weekday()]
    month = common_texts.MONTHS[detail.tournament.date.month]
    public_card = public_tournament_card(
        name=type_name(detail.tournament),
        description=detail.description,
        economy=detail.economy,
        date_label=f"{weekday}, {detail.tournament.date.day} {month}",
    )
    parameters = _admin_parameters(
        detail,
        show_creatable_status=False,
        knockout_small_points=detail.knockout_small_points,
        knockout_big_points=detail.knockout_big_points,
        knockout_main_points=detail.knockout_main_points,
        knockout_main_final_points=detail.knockout_main_final_points,
    )
    operational = [
        f"Зарегистрировано: {registrations_count}",
        "Регистрация: " + ("открыта" if detail.tournament.registration_open else "закрыта"),
    ]
    return "\n\n".join([public_card, "\n".join(parameters), "\n".join(operational)])


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
    return day.tournament.tournament_type_calendar_code or "?"


def _calendar_legend(view: object) -> list[str]:
    return [
        _calendar_legend_line(tournament_type)
        for tournament_type in getattr(view, "tournament_types", ())
    ]


def _calendar_legend_line(tournament_type: object) -> str:
    if tournament_type.calendar_code == "?":
        return "? — тип не определён"
    return f"{tournament_type.calendar_code} — {tournament_type.name}"


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


def public_tournament_card(
    *,
    name: str,
    description: str | None,
    economy: object | None,
    date_label: str | None = None,
) -> str:
    sections: list[str] = []
    if date_label is not None:
        sections.append(f"🗓 {escape(date_label)}")
    sections.append(f"<b>{escape(name.upper())}</b>")
    if description:
        sections.append(escape(description))
    if economy is not None:
        sections.extend(_economy_sections(economy))
    return "\n\n".join(sections)


def _economy_sections(economy: object) -> list[str]:
    sections = [
        "<b>Вход:</b>\n"
        f"💵 {fmt_common.number(economy.entry_fee)} ₽ — "
        f"{fmt_common.number(economy.entry_stack)} фишек"
    ]
    if economy.rebuys:
        sections.append(
            "<b>Ребаи:</b>\n"
            + "\n".join(
                f"{_number_marker(index)} {fmt_common.number(rebuy.fee)} ₽ — "
                f"{fmt_common.number(rebuy.stack)} фишек"
                for index, rebuy in enumerate(economy.rebuys, start=1)
            )
        )
    if economy.addon_fee > 0 and economy.addon_stack > 0:
        sections.append(
            "<b>Аддон:</b>\n"
            f"➕ {fmt_common.number(economy.addon_fee)} ₽ — "
            f"{fmt_common.number(economy.addon_stack)} фишек"
        )
    return sections


def _admin_tournament_card(view: object, *, show_creatable_status: bool) -> str:
    public_card = public_tournament_card(
        name=view.name,
        description=view.description,
        economy=view.economy,
    )
    return "\n\n".join(
        [
            public_card,
            "\n".join(_admin_parameters(view, show_creatable_status=show_creatable_status)),
        ]
    )


def _admin_parameters(
    view: object,
    *,
    show_creatable_status: bool,
    knockout_small_points: int | None = None,
    knockout_big_points: int | None = None,
    knockout_main_points: int | None = None,
    knockout_main_final_points: int | None = None,
) -> list[str]:
    calendar_code = getattr(view, "calendar_code", None)
    if calendar_code is None:
        calendar_code = view.tournament.tournament_type_calendar_code or "?"
    lines = [
        "<b>⚙️ Параметры (не видны игрокам)</b>",
        f"🟢 Код формата: {escape(calendar_code)}",
    ]
    if show_creatable_status:
        lines.append(
            "🟢 Статус: доступен для создания"
            if view.is_creatable
            else "⚪ Статус: недоступен для создания"
        )
    rules = view.rules
    if rules is None or rules.knockout_mode == "none":
        lines.append("⚪ Нокауты: выключены")
    else:
        knockout_text = _knockout_parameters(
            rules.knockout_mode,
            small=knockout_small_points,
            big=knockout_big_points,
            main=knockout_main_points,
            main_final=knockout_main_final_points,
        )
        lines.append(f"🟢 Нокауты: {knockout_text}")
    lines.append(
        "🟢 Бонусные очки: включены"
        if rules is not None and rules.supports_bonus_points
        else "⚪ Бонусные очки: выключены"
    )
    if rules is not None and rules.points_multiplier != 1:
        lines.append(f"🟢 Множитель турнирных очков: ×{_decimal_ru(rules.points_multiplier)}")
    else:
        lines.append("⚪ Множитель турнирных очков: выключен")
    individual = _individual_multiplier_lines(rules)
    if individual:
        lines.extend(["🟢 Множители отдельных призовых мест:", *individual])
    else:
        lines.append("⚪ Множители отдельных призовых мест: выключены")
    return lines


def _knockout_parameters(
    mode: str,
    *,
    small: int | None,
    big: int | None,
    main: int | None,
    main_final: int | None,
) -> str:
    if mode == "small":
        return f"KO — {small}" if small is not None else "KO"
    if mode == "small_big":
        if small is not None and big is not None:
            return f"KO — {small}, BKO — {big}"
        return "KO и BKO"
    if mode == "main_ko":
        if main is not None and main_final is not None:
            return f"KO — {main}, BKO — {main_final}"
        return "KO и BKO"
    return escape(mode)


def _individual_multiplier_lines(rules: object | None) -> list[str]:
    if rules is None or rules.prize_place_multiplier == 1:
        return []
    # The current domain stores one shared coefficient for every selected place.
    # A future constructor must not imply independently configurable place values.
    places = _prize_places(rules.prize_place_multiplier_places)
    return [
        f"    {_number_marker(place)} — ×{_decimal_ru(rules.prize_place_multiplier)}"
        for place in places
    ]


def _prize_places(raw_places: str | None) -> tuple[int, ...]:
    if not raw_places:
        return ()
    try:
        return parse_prize_multiplier_places(raw_places)
    except PrizeMultiplierPlacesError:
        return ()


def _number_marker(value: int) -> str:
    keycaps = ("1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟")
    if 1 <= value <= len(keycaps):
        return keycaps[value - 1]
    return f"{value}."


def _decimal_ru(value: object) -> str:
    return fmt_common.decimal(value).replace(".", ",")
