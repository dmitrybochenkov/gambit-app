from app.bot.telegram.texts import common as common_texts
from app.bot.telegram.texts.user import tournaments as tournament_texts


def label(tournament: object) -> str:
    weekday = common_texts.WEEKDAYS[tournament.date.weekday()]
    month = common_texts.MONTHS[tournament.date.month]
    return f"{weekday}, {tournament.date.day} {month} — {type_name(tournament)}"


def schedule(tournaments: list) -> str:
    if not tournaments:
        return tournament_texts.TOURNAMENTS_EMPTY

    lines = [tournament_texts.TOURNAMENT_SCHEDULE_TITLE, ""]
    for tournament in tournaments:
        lines.append(f"{label(tournament)}")
    return "\n".join(lines)


def type_name(tournament: object) -> str:
    if tournament.tournament_type_name is not None:
        return tournament.tournament_type_name
    return tournament_texts.TOURNAMENT_TYPE_FALLBACK
