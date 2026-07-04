from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import Player, ScoringConfig, Season, Tournament
from app.db.models.enums import SeasonStatus, TournamentStatus


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
            type=1,
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
