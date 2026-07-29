from app.domain.scoring import TournamentScoring


def test_default_knockout_points_are_domain_constants() -> None:
    assert TournamentScoring.KNOCKOUT_POINTS == 15
    assert TournamentScoring.BIG_KNOCKOUT_POINTS == 60
