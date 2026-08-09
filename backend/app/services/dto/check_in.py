from dataclasses import dataclass

from app.services.dto.tournaments import TournamentView


@dataclass(frozen=True)
class CheckInCandidateView:
    user_id: int
    display_name: str
    is_pre_registered: bool
    is_checked_in: bool
    source: str | None = None
    has_result_data: bool = False


@dataclass(frozen=True)
class TournamentCheckInView:
    tournament: TournamentView
    registered_count: int
    registered_checked_in_count: int
    checked_in_count: int
    walk_in_count: int
