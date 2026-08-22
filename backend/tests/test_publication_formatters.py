from datetime import date
from decimal import Decimal

from app.bot.telegram.formatters import publications as publication_fmt
from app.services.dto.results import (
    TournamentCombinationView,
    TournamentPhotoView,
    TournamentPublicationDestinationView,
    TournamentPublicationKnockoutView,
    TournamentPublicationPlaceView,
    TournamentResultPublicationView,
)
from app.services.dto.tournaments import TournamentView


def test_result_publication_report_uses_saved_points_and_evening_combinations() -> None:
    view = TournamentResultPublicationView(
        tournament=TournamentView(
            id=1,
            date=date(2026, 8, 9),
            tournament_type_id=10,
            tournament_type_name="Баунти турнир",
            tournament_type_code="bounty",
        ),
        tournament_fund=1500,
        places=[
            TournamentPublicationPlaceView(
                place=1,
                display_name="Агафонов Павел",
                total_points=Decimal("42.5"),
            ),
            TournamentPublicationPlaceView(
                place=2,
                display_name="Рыжов Евгений",
                total_points=Decimal("31"),
            ),
        ],
        top_knockouters=[
            TournamentPublicationKnockoutView(
                display_name="Агафонов Павел",
                knockouts_count=7,
                big_knockouts_count=1,
            ),
            TournamentPublicationKnockoutView(
                display_name="Рыжов Евгений",
                knockouts_count=0,
                big_knockouts_count=2,
            ),
        ],
        combinations=[
            TournamentCombinationView(
                id=1,
                tournament_id=1,
                player_id=100,
                display_name="Агафонов Павел",
                combination_type="straight_flush",
            )
        ],
        photos=[
            TournamentPhotoView(
                id=1,
                tournament_id=1,
                telegram_file_id="photo",
                telegram_file_unique_id="unique-photo",
                position=1,
            )
        ],
        destinations=[
            TournamentPublicationDestinationView(
                destination_type="group",
                chat_id=-100,
                already_published=False,
            )
        ],
        content_hash="hash",
    )

    text = publication_fmt.result_publication_report(view)

    assert "ИТОГИ БАУНТИ ТУРНИР 🏆" in text
    assert "Фонд турнира составил 1 500 очков!" in text
    assert "1️⃣ Агафонов Павел — 43 очков" in text
    assert "2️⃣ Рыжов Евгений — 31 очков" in text
    assert "Агафонов Павел — 7 K.O. + 1 BOSS" in text
    assert "Рыжов Евгений — 2 BOSS" in text
    assert "Агафонов Павел — Стрит-флеш" in text
    assert "Игра ведётся исключительно на рейтинг" in text
