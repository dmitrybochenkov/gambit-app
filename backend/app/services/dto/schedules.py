from dataclasses import dataclass


@dataclass(frozen=True)
class TournamentRebuyView:
    fee: int
    stack: int
