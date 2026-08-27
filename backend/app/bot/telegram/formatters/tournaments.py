from app.bot.telegram.formatters import common as fmt_common
from app.bot.telegram.texts import common as common_texts
from app.bot.telegram.texts.superadmin import tournaments as superadmin_tournament_texts
from app.bot.telegram.texts.user import tournaments as tournament_texts
from app.domain.prize_multiplier_places import (
    PrizeMultiplierPlacesError,
    parse_prize_multiplier_places,
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


def type_name(tournament: object) -> str:
    if tournament.tournament_type_name is not None:
        return tournament.tournament_type_name
    return tournament_texts.TOURNAMENT_TYPE_FALLBACK


def short_label(tournament: object) -> str:
    return f"{tournament.date.day:02d}.{tournament.date.month:02d} — {type_name(tournament)}"


def _readiness_reasons(readiness: object) -> list[str]:
    if not readiness.reasons:
        return ["Результаты заполнены не полностью."]
    return [f"• {reason}" for reason in readiness.reasons]


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
