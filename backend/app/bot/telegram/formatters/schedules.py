from app.bot.telegram.formatters import common as fmt_common
from app.bot.telegram.texts import common as common_texts
from app.bot.telegram.texts.admin import calendar as calendar_texts
from app.domain.prize_multiplier_places import (
    PrizeMultiplierPlacesError,
    parse_prize_multiplier_places,
)

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


def prompt(prompt: object) -> str:
    lines = [calendar_texts.TOURNAMENTS_MANUAL_PROPOSAL_TITLE, ""]
    for item in prompt.tournaments:
        lines.append(_prompt_item_label(item))
    return "\n".join(lines)


def created_prompt(prompt: object) -> str:
    lines = [calendar_texts.TOURNAMENTS_CREATED_TITLE, ""]
    for item in prompt.tournaments:
        lines.append(_prompt_item_label(item))
    return "\n".join(lines)


def public_weekly(schedule: object) -> list[str]:
    blocks = [
        _public_tournament(tournament)
        for tournament in sorted(schedule.tournaments, key=lambda item: (item.date, item.id))
    ]
    return _split_messages(blocks)


def _prompt_item_label(item: object) -> str:
    weekday = common_texts.WEEKDAYS[item.date.weekday()]
    month = common_texts.MONTHS[item.date.month]
    return f"{weekday}, {item.date.day} {month} — {item.tournament_type.name}"


def _public_tournament(
    tournament: object,
) -> str:
    lines = [
        f"🗓 {common_texts.WEEKDAYS[tournament.date.weekday()].upper()} — "
        f"{tournament.tournament_type_name.upper()}",
    ]
    description_lines = _description_lines(tournament)
    if description_lines:
        lines.extend(description_lines)
        lines.append("")
    lines.extend(
        [
            "💰 Условия участия",
            f"Вход: {fmt_common.number(tournament.entry_fee)} ₽ — "
            f"{fmt_common.number(tournament.entry_stack)} фишек",
        ]
    )
    if len(tournament.rebuys) == 1:
        rebuy = tournament.rebuys[0]
        lines.append(
            f"Ребай: {fmt_common.number(rebuy.fee)} ₽ — {fmt_common.number(rebuy.stack)} фишек"
        )
    elif len(tournament.rebuys) > 1:
        lines.extend(
            [
                "",
                "Ребаи:",
                f"{' / '.join(fmt_common.number(rebuy.fee) for rebuy in tournament.rebuys)} ₽",
                (
                    f"{' / '.join(fmt_common.number(rebuy.stack) for rebuy in tournament.rebuys)} "
                    "фишек"
                ),
            ]
        )
    if tournament.addon_fee > 0 and tournament.addon_stack > 0:
        lines.extend(
            [
                "",
                "Аддон:",
                f"{fmt_common.number(tournament.addon_fee)} ₽ — "
                f"{fmt_common.number(tournament.addon_stack)} фишек",
            ]
        )
    return "\n".join(lines)


def _description_lines(
    tournament: object,
) -> list[str]:
    lines = list(PUBLIC_TOURNAMENT_DESCRIPTIONS.get(tournament.tournament_type_code, []))
    if not lines and tournament.description:
        lines.append(tournament.description)
    if tournament.tournament_type_code == "freezeout":
        bonus_line = _prize_multiplier_line(tournament)
        if bonus_line is not None:
            lines.append(bonus_line)
    return lines


def _prize_multiplier_line(tournament: object) -> str | None:
    if tournament.prize_place_multiplier <= 1 or not tournament.prize_place_multiplier_places:
        return None
    try:
        places = " и ".join(
            str(place)
            for place in parse_prize_multiplier_places(tournament.prize_place_multiplier_places)
        )
    except PrizeMultiplierPlacesError:
        return None
    return f"• Рейтинг за {places} место ×{fmt_common.decimal(tournament.prize_place_multiplier)}"


def _split_messages(blocks: list[str]) -> list[str]:
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
