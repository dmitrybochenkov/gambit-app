from datetime import date
from decimal import Decimal
from pathlib import Path

from conftest import seed_tournament_types_async, tournament_type_id
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import (
    Player,
    ScoringConfig,
    Season,
    Tournament,
    TournamentRegistration,
    TournamentResult,
    TournamentResultDraft,
    TournamentTypeRule,
)
from app.db.models.enums import (
    KnockoutMode,
    PlayerRole,
    PlayerStatus,
    RegistrationStatus,
    SeasonStatus,
    TournamentStatus,
)
from app.services.result_service import ResultService, ResultValidationError


async def test_result_draft_closes_tournament(tmp_path: Path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'results.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        config = ScoringConfig(
            place_1_coefficient=Decimal("0.40"),
            place_5_coefficient=Decimal("0.10"),
            knockout_small_points=10,
            knockout_big_points=50,
        )
        session.add(config)
        await session.flush()
        await seed_tournament_types_async(session)
        session.add(
            TournamentTypeRule(
                tournament_type_id=tournament_type_id("boss_bounty"),
                knockout_mode=KnockoutMode.SMALL_BIG,
            )
        )
        season = Season(
            name="Test season",
            scoring_config_id=config.id,
            starts_at=date(2026, 7, 1),
            ends_at=date(2026, 12, 31),
            status=SeasonStatus.ACTIVE,
        )
        admin = Player(
            telegram_id=100,
            full_name="Admin",
            status=PlayerStatus.ACTIVE,
            role=PlayerRole.ADMIN,
        )
        first_player = Player(
            telegram_id=101,
            full_name="First",
            status=PlayerStatus.ACTIVE,
        )
        second_player = Player(
            telegram_id=102,
            full_name="Second",
            status=PlayerStatus.ACTIVE,
        )
        session.add_all([season, admin, first_player, second_player])
        await session.flush()
        tournament = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("boss_bounty"),
            date=date(2026, 7, 18),
            capacity=30,
            status=TournamentStatus.ACTIVE,
        )
        session.add(tournament)
        await session.flush()
        session.add_all(
            [
                TournamentRegistration(
                    tournament_id=tournament.id,
                    player_id=first_player.id,
                    status=RegistrationStatus.REGISTERED,
                ),
                TournamentRegistration(
                    tournament_id=tournament.id,
                    player_id=second_player.id,
                    status=RegistrationStatus.REGISTERED,
                ),
            ]
        )
        await session.commit()
        tournament_id = tournament.id
        first_player_id = first_player.id
        second_player_id = second_player.id

    service = ResultService(session_factory)
    draft = await service.get_or_create_draft(100, tournament_id)

    assert [player.player_id for player in draft.players] == [
        first_player_id,
        second_player_id,
    ]
    assert await service.validate_draft(100, tournament_id) == ["Введи пул турнира."]

    await service.set_points_pool(100, tournament_id, Decimal("1000"))
    await service.update_player_result(
        100,
        tournament_id,
        first_player_id,
        place=1,
        knockouts_count=2,
        boss_knockouts_count=1,
    )
    await service.update_player_result(
        100,
        tournament_id,
        second_player_id,
        place=None,
        knockouts_count=1,
        boss_knockouts_count=0,
    )
    closed = await service.close_tournament(100, tournament_id)

    assert closed.points_pool == Decimal("1000.00")
    async with session_factory() as session:
        results = list(
            (
                await session.execute(
                    select(TournamentResult).order_by(TournamentResult.player_id)
                )
            ).scalars()
        )
        drafts = list((await session.execute(select(TournamentResultDraft))).scalars())
        tournament = await session.get(Tournament, tournament_id)

    assert drafts == []
    assert tournament is not None
    assert tournament.status == TournamentStatus.CLOSED
    assert len(results) == 2
    assert results[0].tournament_points == Decimal("400.00")
    assert results[0].knockout_points == Decimal("70.00")
    assert results[1].tournament_points == Decimal("0.00")
    assert results[1].knockout_points == Decimal("10.00")
    await engine.dispose()


async def test_result_draft_rejects_duplicate_places(tmp_path: Path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'duplicates.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        config = ScoringConfig()
        session.add(config)
        await session.flush()
        await seed_tournament_types_async(session)
        season = Season(
            name="Test season",
            scoring_config_id=config.id,
            starts_at=date(2026, 7, 1),
            ends_at=date(2026, 12, 31),
            status=SeasonStatus.ACTIVE,
        )
        admin = Player(
            telegram_id=100,
            full_name="Admin",
            status=PlayerStatus.ACTIVE,
            role=PlayerRole.ADMIN,
        )
        players = [
            Player(telegram_id=101, full_name="First", status=PlayerStatus.ACTIVE),
            Player(telegram_id=102, full_name="Second", status=PlayerStatus.ACTIVE),
        ]
        session.add_all([season, admin, *players])
        await session.flush()
        tournament = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 7, 18),
            capacity=30,
            status=TournamentStatus.ACTIVE,
            points_pool=Decimal("1000"),
        )
        session.add(tournament)
        await session.flush()
        session.add_all(
            TournamentRegistration(
                tournament_id=tournament.id,
                player_id=player.id,
                status=RegistrationStatus.REGISTERED,
            )
            for player in players
        )
        await session.commit()
        tournament_id = tournament.id
        player_ids = [player.id for player in players]

    service = ResultService(session_factory)
    for player_id in player_ids:
        await service.update_player_result(
            100,
            tournament_id,
            player_id,
            place=1,
            knockouts_count=0,
            boss_knockouts_count=0,
        )

    try:
        await service.close_tournament(100, tournament_id)
    except ResultValidationError as error:
        assert error.errors == ["Дублируются места: 1."]
    else:
        raise AssertionError("Expected ResultValidationError")
    await engine.dispose()
