from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class TournamentView:
    id: int
    date: date
    tournament_type_id: int
    tournament_type_name: str | None
    tournament_type_code: str | None = None
