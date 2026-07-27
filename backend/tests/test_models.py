from decimal import Decimal

from app.db.factories import create_user
from app.db.models import TournamentResult


def test_player_display_name() -> None:
    player = create_user(
        telegram_id=123,
        display_name="Ivan Ivanov",
    )

    assert player.display_name == "Ivan Ivanov"


def test_tournament_result_total_points() -> None:
    result = TournamentResult(
        tournament_id=1,
        player_id=1,
        place=1,
        tournament_points=Decimal("45"),
        knockout_points=Decimal("30"),
        bonus_points=Decimal("5"),
    )

    assert result.total_points == Decimal("80")
