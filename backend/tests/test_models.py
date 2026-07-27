from decimal import Decimal

from app.db.models import Player, TournamentResult


def test_player_display_name() -> None:
    player = Player(
        telegram_id=123,
        display_name="Ivan Ivanov",
        display_name_normalized="ivan ivanov",
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
