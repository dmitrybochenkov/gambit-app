from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class PointsRatingView:
    player_id: int
    display_name: str
    total_points: Decimal
    tournaments_count: int
    season_champion_titles_count: int = 0


@dataclass(frozen=True)
class KnockoutsRatingView:
    player_id: int
    display_name: str
    knockouts_count: int
    big_knockouts_count: int
    knockout_tournaments_count: int
    season_champion_titles_count: int = 0
    season_knockout_leader_titles_count: int = 0

    @property
    def total_knockouts_count(self) -> int:
        return self.knockouts_count + self.big_knockouts_count


@dataclass(frozen=True)
class RatingResultView:
    title: str
    rows: list[PointsRatingView] | list[KnockoutsRatingView]
    current_player_id: int
