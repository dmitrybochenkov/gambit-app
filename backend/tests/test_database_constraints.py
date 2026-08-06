from datetime import date
from decimal import Decimal

import pytest
from conftest import seed_tournament_types, tournament_type_id
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.factories import create_user
from app.db.models import ScoringConfig, Season, Tournament, TournamentResult, User
from app.db.models.enums import TournamentStatus, UserStatus


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        yield session

    engine.dispose()


def test_player_requires_display_name(session: Session) -> None:
    session.add(User(telegram_id=1, display_name_normalized="test"))

    with pytest.raises(IntegrityError):
        session.commit()


def test_closed_tournament_requires_tournament_fund(session: Session) -> None:
    scoring_config = ScoringConfig()
    session.add(scoring_config)
    session.flush()
    seed_tournament_types(session)

    season = Season(
        name="Season 1",
        scoring_config_id=scoring_config.id,
        starts_at=date(2026, 1, 1),
        ends_at=None,
    )
    session.add(season)
    session.commit()

    session.add(
        Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("bounty"),
            date=date(2026, 7, 4),
            tournament_fund=None,
            status=TournamentStatus.CLOSED,
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()


def test_tournament_date_must_be_unique(session: Session) -> None:
    scoring_config = ScoringConfig()
    session.add(scoring_config)
    session.flush()
    seed_tournament_types(session)

    season = Season(
        name="Season 1",
        scoring_config_id=scoring_config.id,
        starts_at=date(2026, 1, 1),
        ends_at=None,
    )
    session.add(season)
    session.flush()
    session.add_all(
        [
            Tournament(
                season_id=season.id,
                tournament_type_id=tournament_type_id("bounty"),
                date=date(2026, 7, 4),
                status=TournamentStatus.ACTIVE,
            ),
            Tournament(
                season_id=season.id,
                tournament_type_id=tournament_type_id("classic"),
                date=date(2026, 7, 4),
                status=TournamentStatus.ACTIVE,
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        session.commit()


def test_scoring_coefficients_must_total_one(session: Session) -> None:
    session.add(
        ScoringConfig(
            place_1_coefficient=Decimal("0.40"),
            place_2_coefficient=Decimal("0.25"),
            place_3_coefficient=Decimal("0.15"),
            place_4_coefficient=Decimal("0.10"),
            place_5_coefficient=Decimal("0.05"),
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()


def test_season_may_have_valid_end_date(session: Session) -> None:
    scoring_config = ScoringConfig()
    session.add(scoring_config)
    session.flush()

    session.add(
        Season(
            name="Season 1",
            scoring_config_id=scoring_config.id,
            starts_at=date(2026, 1, 1),
            ends_at=date(2026, 12, 31),
        )
    )

    session.commit()


def test_season_may_be_open_ended(session: Session) -> None:
    scoring_config = ScoringConfig()
    session.add(scoring_config)
    session.flush()

    session.add(
        Season(
            name="Season 1",
            scoring_config_id=scoring_config.id,
            starts_at=date(2026, 1, 1),
            ends_at=None,
        )
    )

    session.commit()


def test_closed_season_end_date_must_not_precede_start_date(session: Session) -> None:
    scoring_config = ScoringConfig()
    session.add(scoring_config)
    session.flush()

    session.add(
        Season(
            name="Season 1",
            scoring_config_id=scoring_config.id,
            starts_at=date(2026, 1, 2),
            ends_at=date(2026, 1, 1),
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()


def test_database_rejects_multiple_open_ended_seasons(
    session: Session,
) -> None:
    scoring_config = ScoringConfig()
    session.add(scoring_config)
    session.flush()

    session.add_all(
        [
            Season(
                name="Season 1",
                scoring_config_id=scoring_config.id,
                starts_at=date(2026, 1, 1),
                ends_at=None,
            ),
            Season(
                name="Season 2",
                scoring_config_id=scoring_config.id,
                starts_at=date(2026, 6, 1),
                ends_at=None,
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        session.commit()


def test_tournament_result_bonus_points_must_be_nonnegative(
    session: Session,
) -> None:
    scoring_config = ScoringConfig()
    player = create_user(
        telegram_id=1,
        display_name="Игрок Первый",
        status=UserStatus.ACTIVE,
    )
    session.add_all([scoring_config, player])
    session.flush()
    seed_tournament_types(session)

    season = Season(
        name="Season 1",
        scoring_config_id=scoring_config.id,
        starts_at=date(2026, 1, 1),
        ends_at=None,
    )
    session.add(season)
    session.flush()
    tournament = Tournament(
        season_id=season.id,
        tournament_type_id=tournament_type_id("bounty"),
        date=date(2026, 7, 4),
        status=TournamentStatus.ACTIVE,
    )
    session.add(tournament)
    session.flush()

    session.add(
        TournamentResult(
            tournament_id=tournament.id,
            player_id=player.id,
            place=1,
            knockouts_count=0,
            big_knockouts_count=0,
            tournament_points=Decimal("0"),
            knockout_points=Decimal("0"),
            bonus_points=Decimal("-1"),
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()
