from app.bot.telegram.formatters import common as fmt_common
from app.bot.telegram.formatters import tournaments as tournament_fmt
from app.bot.telegram.texts import common as common_texts

COMBINATION_LABELS = {
    "four_of_a_kind": "Каре",
    "straight_flush": "Стрит-флеш",
    "royal_flush": "Роял-флеш",
}
PLACE_EMOJIS = {1: "1️⃣", 2: "2️⃣", 3: "3️⃣", 4: "4️⃣", 5: "5️⃣"}

RESULTS_FOOTER = "Игра ведётся исключительно на рейтинг, без использования денежных средств ❗️18+"
WINNER_CONGRATULATIONS = "Поздравляем победителей турнира!!! 🏆"
CAPTION_LIMIT = 1024
MESSAGE_LIMIT = 4096
SCHEDULE_HEADER = "🔥 РАСПИСАНИЕ ТУРНИРОВ ПОКЕРНОГО КЛУБА «ГАМБИТ»\n\n🔥♠️♥️♣️♦️"
SCHEDULE_SEPARATOR = "━━━━━━━━━━━━━━"


def result_publication_preview(view: object) -> str:
    return result_publication_report(view)


def result_publication_report(view: object) -> str:
    lines = [
        "ЕЖЕДНЕВНЫЙ ОТЧЁТ 🏆",
        "",
        f"ИТОГИ {tournament_fmt.type_name(view.tournament).upper()} 🏆",
        "",
        f"Фонд турнира составил {fmt_common.number(view.tournament_fund)} очков!",
        "",
    ]
    lines.extend(
        f"{PLACE_EMOJIS.get(place.place, str(place.place))} {place.display_name} — "
        f"{fmt_common.points(place.total_points)} очков"
        for place in view.places
    )
    lines.extend(["", WINNER_CONGRATULATIONS])
    if view.top_knockouters:
        lines.extend(["", "Топ-3 НОКАУТЕРОВ:", ""])
        lines.extend(_knockout_line(player) for player in view.top_knockouters)
    if view.combinations:
        lines.extend(["", "Комбинации вечера:", ""])
        lines.extend(
            f"{combination.display_name} — {combination_label(combination.combination_type)}"
            for combination in view.combinations
        )
    lines.extend(["", RESULTS_FOOTER])
    return "\n".join(lines)


def schedule_publication_preview(view: object) -> str:
    return schedule_publication_report(view)


def schedule_publication_report(view: object) -> str:
    blocks = _schedule_tournament_blocks(view.tournaments)
    if not blocks:
        return SCHEDULE_HEADER
    return f"{SCHEDULE_HEADER}\n\n{_join_schedule_blocks(blocks)}"


def schedule_publication_messages(
    view: object,
    *,
    limit: int = MESSAGE_LIMIT,
) -> list[str]:
    blocks = _schedule_tournament_blocks(view.tournaments)
    if not blocks:
        return [SCHEDULE_HEADER]

    messages: list[str] = []
    current = SCHEDULE_HEADER
    for index, block in enumerate(blocks):
        next_block = block if index == 0 or not current else f"{SCHEDULE_SEPARATOR}\n\n{block}"
        candidate = f"{current}\n\n{next_block}" if current else next_block
        if len(candidate) <= limit:
            current = candidate
            continue
        messages.append(current)
        if len(next_block) <= limit:
            current = next_block
            continue
        block_parts = _split_text_by_paragraphs(next_block, limit)
        messages.extend(block_parts[:-1])
        current = block_parts[-1]
    if current:
        messages.append(current)
    return messages


def publication_summary(summary: object) -> str:
    title = (
        "Результаты опубликованы частично."
        if summary.has_failures
        else "Результаты опубликованы ✅"
    )
    lines = [title, ""]
    for item in summary.results:
        destination = "Группа" if item.destination_type == "group" else "Канал"
        status = "✅" if item.sent or item.already_published else "❌"
        lines.append(f"{destination}: {status}")
    return "\n".join(lines)


def schedule_publication_summary(summary: object) -> str:
    title = (
        "Расписание опубликовано частично."
        if summary.has_failures
        else "Расписание опубликовано ✅"
    )
    lines = [title, ""]
    for item in summary.results:
        destination = "Группа" if item.destination_type == "group" else "Канал"
        status = "✅" if item.sent or item.already_published else "❌"
        lines.append(f"{destination}: {status}")
    return "\n".join(lines)


def combination_label(value: str) -> str:
    return COMBINATION_LABELS.get(value, value)


def _knockout_line(player: object) -> str:
    parts = []
    if player.knockouts_count > 0:
        parts.append(f"{player.knockouts_count} K.O.")
    if player.big_knockouts_count > 0:
        parts.append(f"{player.big_knockouts_count} BOSS")
    return f"{player.display_name} — {' + '.join(parts)}"


def _schedule_tournament_blocks(tournaments: list[object]) -> list[str]:
    return [_schedule_tournament_block(tournament) for tournament in tournaments]


def _join_schedule_blocks(blocks: list[str]) -> str:
    return f"\n\n{SCHEDULE_SEPARATOR}\n\n".join(blocks)


def _schedule_tournament_block(tournament: object) -> str:
    weekday = common_texts.WEEKDAYS[tournament.date.weekday()].upper()
    lines = [f"🗓 {weekday} — {tournament.tournament_type_name.upper()}"]
    if tournament.description:
        lines.extend(["", str(tournament.description).strip()])
    if tournament.economy is not None:
        lines.extend(["", *_schedule_economy_lines(tournament.economy)])
    return "\n".join(lines)


def _schedule_economy_lines(economy: object) -> list[str]:
    lines = [
        "💰 Условия участия",
        "",
        f"Вход: {fmt_common.number(economy.entry_fee)} ₽ — "
        f"{fmt_common.number(economy.entry_stack)} фишек",
    ]
    if economy.rebuys:
        lines.extend(
            [
                "",
                "Ребаи:",
                "",
                f"{' / '.join(fmt_common.number(rebuy.fee) for rebuy in economy.rebuys)} ₽",
                "",
                f"{' / '.join(fmt_common.number(rebuy.stack) for rebuy in economy.rebuys)} фишек",
            ]
        )
    if economy.addon_fee > 0 and economy.addon_stack > 0:
        lines.extend(
            [
                "",
                "Аддон:",
                "",
                f"{fmt_common.number(economy.addon_fee)} ₽ — "
                f"{fmt_common.number(economy.addon_stack)} фишек",
            ]
        )
    return lines


def _split_text_by_paragraphs(text: str, limit: int) -> list[str]:
    paragraphs = text.split("\n\n")
    messages: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            messages.append(current)
        if len(paragraph) <= limit:
            current = paragraph
            continue
        messages.extend(
            paragraph[index : index + limit] for index in range(0, len(paragraph), limit)
        )
        current = ""
    if current:
        messages.append(current)
    return messages
