from decimal import Decimal

from app.db.models import Tournament
from app.db.repositories.rating_repository import (
    KnockoutsRatingRow,
    PointsRatingRow,
)

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


def format_rating(
    title: str,
    rows: list[PointsRatingRow] | list[KnockoutsRatingRow],
) -> str:
    if not rows:
        return f"{title}\n\nВ рейтинге пока нет данных."

    lines = [title, ""]
    for position, row in enumerate(rows, start=1):
        if isinstance(row, PointsRatingRow):
            points = _format_decimal(row.total_points)
            lines.append(
                f"{position}. {row.display_name} — {points} очков "
                f"(турниров: {row.tournaments_count})"
            )
        else:
            lines.append(
                f"{position}. {row.display_name} — "
                f"всего КО: {row.total_knockouts_count}, "
                f"Босс КО: {row.boss_knockouts_count}"
            )
    return "\n".join(lines)


def _format_decimal(value: Decimal) -> str:
    return format(value.normalize(), "f")
