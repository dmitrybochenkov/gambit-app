from datetime import date

from app.bot.telegram.texts import common


def tournament_type_prompt(tournament_date: date) -> str:
    weekday = common.WEEKDAYS[tournament_date.weekday()]
    month = common.MONTHS[tournament_date.month]
    return f"Выбери тип турнира:\n{weekday}, {tournament_date.day} {month}"
