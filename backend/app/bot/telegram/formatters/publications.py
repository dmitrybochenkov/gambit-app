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
    lines = ["РАСПИСАНИЕ ТУРНИРОВ", ""]
    for tournament in view.tournaments:
        weekday = common_texts.WEEKDAYS[tournament.date.weekday()]
        month = common_texts.MONTHS[tournament.date.month]
        lines.append(
            f"{weekday}, {tournament.date.day} {month} — {tournament.tournament_type_name}"
        )
    return "\n".join(lines)


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
