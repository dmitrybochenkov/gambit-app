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

    @property
    def entered_players(self) -> list[TournamentResultPlayerView]:
        return [player for player in self.players if self.has_entered_result(player)]

    def has_entered_result(self, player: TournamentResultPlayerView) -> bool:
        if player.place is not None:
            return True
        if self.knockout_mode in {"small", "small_big"} and player.knockouts_count > 0:
            return True
        if self.knockout_mode == "small_big" and player.big_knockouts_count > 0:
            return True
        return self.supports_bonus_points and player.bonus_points > 0

    @property
    def required_places(self) -> tuple[int, ...]:
        return tuple(range(1, min(5, len(self.players)) + 1))

    @property
    def bonus_points_label(self) -> str:
        if self.tournament.tournament_type_code == "mystery_bounty":
            return "Доп. очки"
        return "Бонус"
