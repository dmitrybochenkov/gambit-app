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
from app.services.result_service import ResultInvalidPlayerDataError, ResultService


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
        players = [
            Player(
                telegram_id=telegram_id,
                full_name=f"Player {telegram_id}",
                status=PlayerStatus.ACTIVE,
            )
            for telegram_id in range(101, 106)
        ]
        session.add_all([season, admin, *players])
        await session.flush()
        tournament = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("boss_bounty"),
            date=date(2026, 7, 18),
            status=TournamentStatus.ACTIVE,
        )
        session.add(tournament)
        await session.flush()
        session.add_all(
            [
                TournamentRegistration(
                    tournament_id=tournament.id,
                    player_id=player.id,
                    status=RegistrationStatus.REGISTERED,
                )
                for player in players
            ]
        )
        await session.commit()
        tournament_id = tournament.id
        player_ids = [player.id for player in players]

    service = ResultService(session_factory)
    draft = await service.get_or_create_draft(100, tournament_id)

    assert draft.knockout_mode == KnockoutMode.SMALL_BIG.value
    assert [player.player_id for player in draft.players] == player_ids
    assert await service.validate_draft(100, tournament_id) == [
        "Введи пул турнира.",
        "Введи места: 1, 2, 3, 4, 5.",
    ]

    await service.set_points_pool(100, tournament_id, Decimal("1000"))
    await service.update_player_result(
        100,
        tournament_id,
        player_ids[0],
        place=1,
        knockouts_count=2,
        big_knockouts_count=1,
    )
    await service.update_player_result(
        100,
        tournament_id,
        player_ids[1],
        place=2,
        knockouts_count=1,
        big_knockouts_count=0,
    )
    for place, player_id in zip(range(3, 6), player_ids[2:], strict=True):
        await service.update_player_result(
            100,
            tournament_id,
            player_id,
            place=place,
            knockouts_count=0,
            big_knockouts_count=0,
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
    assert len(results) == 5
    assert results[0].tournament_points == Decimal("400.00")
    assert results[0].knockout_points == Decimal("70.00")
    assert results[1].tournament_points == Decimal("250.00")
    assert results[1].knockout_points == Decimal("10.00")
    await engine.dispose()


async def test_result_draft_moves_duplicate_place_to_latest_player(
    tmp_path: Path,
) -> None:
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
            big_knockouts_count=0,
        )

    draft = await service.get_or_create_draft(100, tournament_id)

    assert [(player.player_id, player.place) for player in draft.players] == [
        (player_ids[0], None),
        (player_ids[1], 1),
    ]
    assert await service.validate_draft(100, tournament_id) == [
        "Введи места: 2, 3, 4, 5."
    ]

    try:
        await service.update_player_result(
            100,
            tournament_id,
            player_ids[0],
            place=7,
            knockouts_count=0,
            big_knockouts_count=0,
        )
    except ResultInvalidPlayerDataError:
        pass
    else:
        raise AssertionError("Expected ResultInvalidPlayerDataError")
    await engine.dispose()
