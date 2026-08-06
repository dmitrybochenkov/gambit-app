from sqlalchemy.sql.elements import ColumnElement

from app.db.models import Tournament
from app.db.models.enums import TournamentStatus


def closed_tournament_filter() -> ColumnElement[bool]:
    return Tournament.status == TournamentStatus.CLOSED
