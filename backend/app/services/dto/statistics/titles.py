from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class PlayerTitleKind(StrEnum):
    CHAMPION = "champion"
    KNOCKOUT = "knockout"


@dataclass(frozen=True)
class PlayerTitleOccurrenceView:
    season_id: int
    season_name: str
    season_starts_at: date
    kind: PlayerTitleKind
