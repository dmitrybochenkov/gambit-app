from dataclasses import dataclass
from decimal import Decimal

from app.services.dto.tournaments import TournamentView


@dataclass(frozen=True)
class TournamentResultPlayerView:
    player_id: int
    display_name: str
    place: int | None
    knockouts_count: int
    big_knockouts_count: int
    bonus_points: int = 0
    tournament_points: Decimal = Decimal("0")
    knockout_points: Decimal = Decimal("0")

    @property
    def total_points(self) -> Decimal:
        return self.tournament_points + self.knockout_points + Decimal(self.bonus_points)


@dataclass(frozen=True)
class TournamentResultsView:
    tournament: TournamentView
    tournament_fund: int | None
    players: list[TournamentResultPlayerView]
    knockout_mode: str = "none"
    supports_bonus_points: bool = False
