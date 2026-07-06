from app.db.models import Tournament

WEEKDAYS = {
    0: "Понедельник",
    1: "Вторник",
    2: "Среда",
    3: "Четверг",
    4: "Пятница",
    5: "Суббота",
    6: "Воскресенье",
}

MONTHS = {
    1: "января",
    2: "февраля",
    3: "марта",
    4: "апреля",
    5: "мая",
    6: "июня",
    7: "июля",
    8: "августа",
    9: "сентября",
    10: "октября",
    11: "ноября",
    12: "декабря",
}


def format_tournament_label(tournament: Tournament) -> str:
    weekday = WEEKDAYS[tournament.date.weekday()]
    month = MONTHS[tournament.date.month]
    return (
        f"{weekday}, {tournament.date.day} {month} — "
        f"Турнир {tournament.type}"
    )


def format_tournament_schedule(tournaments: list[Tournament]) -> str:
    if not tournaments:
        return "Ближайших турниров пока нет."

    lines = ["Расписание турниров", ""]
    for tournament in tournaments:
        lines.append(
            f"{format_tournament_label(tournament)} "
            f"(до {tournament.capacity} игроков)"
        )
    return "\n".join(lines)
