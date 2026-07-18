from datetime import date
from decimal import Decimal

import pytest
from conftest import seed_tournament_types, tournament_type_id
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import Player, ScoringConfig, Season, Tournament, TournamentResult
from app.db.models.enums import PlayerStatus, SeasonStatus, TournamentStatus


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        yield session

    engine.dispose()


def test_player_requires_name_or_nickname(session: Session) -> None:
    session.add(Player(telegram_id=1))

    with pytest.raises(IntegrityError):
        session.commit()


def test_closed_tournament_requires_points_pool(session: Session) -> None:
    scoring_config = ScoringConfig()
    session.add(scoring_config)
    session.flush()
    seed_tournament_types(session)

    season = Season(
        name="Season 1",
        scoring_config_id=scoring_config.id,
        starts_at=date(2026, 1, 1),
        ends_at=date(2026, 12, 31),
        status=SeasonStatus.ACTIVE,
    )
    session.add(season)
    session.commit()

    session.add(
        Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("bounty"),
            date=date(2026, 7, 4),
            capacity=30,
            points_pool=None,
            status=TournamentStatus.CLOSED,
        )
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


def test_tournament_result_bonus_points_must_be_nonnegative(
    session: Session,
) -> None:
    scoring_config = ScoringConfig()
    player = Player(
        telegram_id=1,
        full_name="Игрок Первый",
        status=PlayerStatus.ACTIVE,
    )
    session.add_all([scoring_config, player])
    session.flush()
    seed_tournament_types(session)

    season = Season(
        name="Season 1",
        scoring_config_id=scoring_config.id,
        starts_at=date(2026, 1, 1),
        ends_at=date(2026, 12, 31),
        status=SeasonStatus.ACTIVE,
    )
    session.add(season)
    session.flush()
    tournament = Tournament(
        season_id=season.id,
        tournament_type_id=tournament_type_id("bounty"),
        date=date(2026, 7, 4),
        capacity=30,
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
            boss_knockouts_count=0,
            tournament_points=Decimal("0"),
            knockout_points=Decimal("0"),
            bonus_points=Decimal("-1"),
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()
