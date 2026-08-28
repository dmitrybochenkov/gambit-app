from datetime import date
from decimal import Decimal

from app.bot.telegram.formatters import publications as publication_fmt
from app.db.models.enums import UserGender
from app.services.dto.results import (
    SchedulePublicationView,
    TournamentCombinationView,
    TournamentPhotoView,
    TournamentPublicationDestinationView,
    TournamentPublicationKnockoutView,
    TournamentPublicationPlaceView,
    TournamentResultPublicationView,
)
from app.services.dto.schedules import TournamentRebuyView
from app.services.dto.tournaments import (
    TournamentEconomyView,
    TournamentScheduleDetailsView,
    TournamentView,
)


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
                gender=UserGender.FEMALE,
            ),
            TournamentPublicationPlaceView(
                place=2,
                display_name="Рыжов Евгений",
                total_points=Decimal("31"),
                gender=UserGender.MALE,
            ),
            TournamentPublicationPlaceView(
                place=5,
                display_name="Анна",
                total_points=Decimal("20"),
                gender=UserGender.FEMALE,
            ),
            TournamentPublicationPlaceView(
                place=6,
                display_name="Мария",
                total_points=Decimal("10"),
                gender=UserGender.FEMALE,
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
    assert "1️⃣ Агафонов Павел 🌸 — 43 очков" in text
    assert "2️⃣ Рыжов Евгений — 31 очков" in text
    assert "5️⃣ Анна 🌸 — 20 очков" in text
    assert "6 Мария — 10 очков" in text
    assert "Мария 🌸" not in text
    assert "Агафонов Павел — 7 K.O. + 1 BOSS" in text
    assert "Рыжов Евгений — 2 BOSS" in text
    assert "Агафонов Павел — Стрит-флеш" in text
    assert "Игра ведётся исключительно на рейтинг" in text


def test_schedule_publication_report_is_full_db_driven_poster() -> None:
    view = SchedulePublicationView(
        tournaments=[
            TournamentScheduleDetailsView(
                id=1,
                date=date(2026, 8, 26),
                tournament_type_name="Mystery Bounty",
                description="🎁 Награды за нокауты\n\n• Очки в рейтинг\n• Привилегии клуба",
                economy=TournamentEconomyView(
                    entry_fee=600,
                    entry_stack=20000,
                    addon_fee=800,
                    addon_stack=125000,
                    rebuys=[
                        TournamentRebuyView(fee=600, stack=30000),
                        TournamentRebuyView(fee=800, stack=50000),
                    ],
                ),
                rules=None,
            ),
            TournamentScheduleDetailsView(
                id=2,
                date=date(2026, 8, 27),
                tournament_type_name="Классика",
                description=None,
                economy=TournamentEconomyView(
                    entry_fee=1000,
                    entry_stack=40000,
                    addon_fee=0,
                    addon_stack=0,
                    rebuys=[],
                ),
                rules=None,
            ),
        ],
        destinations=[],
        content_hash="hash",
    )

    text = publication_fmt.schedule_publication_report(view)

    assert text.startswith("🔥 РАСПИСАНИЕ ТУРНИРОВ ПОКЕРНОГО КЛУБА «ГАМБИТ»")
    assert "🔥♠️♥️♣️♦️" in text
    assert "🗓 СРЕДА — MYSTERY BOUNTY" in text
    assert "🗓 ЧЕТВЕРГ — КЛАССИКА" in text
    assert "26 августа" not in text
    assert "27 августа" not in text
    assert "🎁 Награды за нокауты" in text
    assert "Вход: 600 ₽ — 20 000 фишек" in text
    assert "600 / 800 ₽" in text
    assert "30 000 / 50 000 фишек" in text
    assert "800 ₽ — 125 000 фишек" in text
    assert "Вход: 1 000 ₽ — 40 000 фишек" in text
    assert text.count("━━━━━━━━━━━━━━") == 1
    assert "Аддон:" in text
    assert text.rfind("Аддон:") < text.find("🗓 ЧЕТВЕРГ")


def test_schedule_publication_messages_split_without_losing_content() -> None:
    view = SchedulePublicationView(
        tournaments=[
            TournamentScheduleDetailsView(
                id=1,
                date=date(2026, 8, 26),
                tournament_type_name="Long Tournament",
                description="Первый абзац\n\n" + "A" * 80,
                economy=None,
                rules=None,
            ),
            TournamentScheduleDetailsView(
                id=2,
                date=date(2026, 8, 27),
                tournament_type_name="Next Tournament",
                description="Второй блок",
                economy=None,
                rules=None,
            ),
        ],
        destinations=[],
        content_hash="hash",
    )

    messages = publication_fmt.schedule_publication_messages(view, limit=120)

    assert len(messages) > 1
    assert messages[0].startswith("🔥 РАСПИСАНИЕ")
    assert all(len(message) <= 120 for message in messages)
    assert "LONG TOURNAMENT" in "\n".join(messages)
    assert "NEXT TOURNAMENT" in "\n".join(messages)
