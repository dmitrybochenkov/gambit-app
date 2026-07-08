import json
from datetime import date
from decimal import Decimal

from app.db.models import AdminPrompt, Tournament
from app.db.repositories.profile_repository import PlayerProfileStats
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


def format_profile(title: str, stats: PlayerProfileStats | None) -> str:
    if stats is None:
        return f"{title}\n\nПрофиль не найден. Нажми /start."

    points = _format_decimal(stats.total_points)
    return "\n".join(
        [
            title,
            "",
            stats.display_name,
            f"Рейтинг: {points} очков",
            f"Количество КО: {stats.total_knockouts_count}",
            f"Количество турниров: {stats.tournaments_count}",
            "Количество призовых мест:",
            f"1 место: {stats.first_places_count}",
            f"2 место: {stats.second_places_count}",
            f"3 место: {stats.third_places_count}",
            f"4 место: {stats.fourth_places_count}",
            f"5 место: {stats.fifth_places_count}",
        ]
    )


def format_admin_calendar_prompt(prompt: AdminPrompt) -> str:
    payload = json.loads(prompt.payload)
    if prompt.kind == "season_proposal":
        starts_at = date.fromisoformat(payload["starts_at"])
        ends_at = date.fromisoformat(payload["ends_at"])
        return "\n".join(
            [
                "Нужно подготовить следующий сезон.",
                "",
                f"Предложение: {payload['name']}",
                f"Период: {format_date(starts_at)} — {format_date(ends_at)}",
                "",
                "Подтвердить создание?",
            ]
        )

    lines = ["Нужно создать турниры на две недели вперед.", ""]
    for item in payload["tournaments"]:
        tournament = Tournament(
            season_id=0,
            type=int(item["type"]),
            date=date.fromisoformat(item["date"]),
            capacity=int(item["capacity"]),
        )
        lines.append(f"• {format_tournament_label(tournament)}")
    lines.extend(["", "Подтвердить создание?"])
    return "\n".join(lines)


def format_date(value: date) -> str:
    return f"{value.day} {MONTHS[value.month]} {value.year}"


def _format_decimal(value: Decimal) -> str:
    return format(value.normalize(), "f")
