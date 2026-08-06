from datetime import date

from app.db.models import Tournament
from app.db.models.enums import TournamentStatus


def is_tournament_closeable(tournament: Tournament, business_date: date) -> bool:
    return tournament.status == TournamentStatus.ACTIVE and tournament.date <= business_date
