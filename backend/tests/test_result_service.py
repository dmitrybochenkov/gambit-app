from datetime import date
from decimal import Decimal
from pathlib import Path

from conftest import build_player, seed_tournament_types_async, tournament_type_id
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import (
    RegistrationRequest,
    ScoringConfig,
    Season,
    Tournament,
    TournamentParticipant,
    TournamentRegistration,
    TournamentResult,
    TournamentResultDraft,
    TournamentTypeRule,
    User,
)
from app.db.models.enums import (
    KnockoutMode,
    RegistrationStatus,
    TournamentParticipantSource,
    TournamentStatus,
    UserRole,
    UserStatus,
)
from app.services.result_service import ResultInvalidPlayerDataError, ResultService
from app.services.tournament_participant_service import TournamentParticipantService


async def test_result_tournament_list_includes_open_past_tournaments(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'open_results.db'}")
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
            ends_at=None,
        )
        admin = build_player(
            telegram_id=100,
            display_name="Admin",
            status=UserStatus.ACTIVE,
            role=UserRole.ADMIN,
        )
        session.add_all([season, admin])
        await session.flush()
        session.add_all(
            [
                Tournament(
                    season_id=season.id,
                    tournament_type_id=tournament_type_id("classic"),
                    date=date(2026, 7, 19),
                    status=TournamentStatus.ACTIVE,
                ),
                Tournament(
                    season_id=season.id,
                    tournament_type_id=tournament_type_id("freezeout"),
                    date=date(2026, 7, 20),
                    status=TournamentStatus.ACTIVE,
                ),
                Tournament(
                    season_id=season.id,
                    tournament_type_id=tournament_type_id("bounty"),
                    date=date(2026, 7, 21),
                    status=TournamentStatus.ACTIVE,
                ),
                Tournament(
                    season_id=season.id,
                    tournament_type_id=tournament_type_id("double_double"),
                    date=date(2026, 7, 18),
                    points_pool=Decimal("1000"),
                    status=TournamentStatus.CLOSED,
                ),
            ]
        )
        await session.commit()

    service = ResultService(session_factory)
    tournaments = await service.list_open_tournaments_for_admin(
        100,
        today=date(2026, 7, 20),
    )

    assert [(tournament.date, tournament.tournament_type_name) for tournament in tournaments] == [
        (date(2026, 7, 19), "Классика"),
        (date(2026, 7, 20), "Фризаут"),
    ]
    await engine.dispose()


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
            ends_at=None,
        )
        admin = build_player(
            telegram_id=100,
            display_name="Admin",
            status=UserStatus.ACTIVE,
            role=UserRole.ADMIN,
        )
        players = [
            build_player(
                telegram_id=telegram_id,
                display_name=f"Player {telegram_id}",
                status=UserStatus.ACTIVE,
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
        session.add_all(
            [
                TournamentParticipant(
                    tournament_id=tournament.id,
                    user_id=player.id,
                    source=TournamentParticipantSource.PRE_REGISTERED,
                    checked_in_by_user_id=admin.id,
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
                await session.execute(select(TournamentResult).order_by(TournamentResult.player_id))
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
            ends_at=None,
        )
        admin = build_player(
            telegram_id=100,
            display_name="Admin",
            status=UserStatus.ACTIVE,
            role=UserRole.ADMIN,
        )
        players = [
            build_player(telegram_id=101, display_name="First", status=UserStatus.ACTIVE),
            build_player(telegram_id=102, display_name="Second", status=UserStatus.ACTIVE),
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
        session.add_all(
            TournamentParticipant(
                tournament_id=tournament.id,
                user_id=player.id,
                source=TournamentParticipantSource.PRE_REGISTERED,
                checked_in_by_user_id=admin.id,
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
    assert await service.validate_draft(100, tournament_id) == ["Введи места: 2, 3, 4, 5."]

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


async def test_result_draft_uses_participants_not_pre_registrations(tmp_path: Path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'participants.db'}")
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
            ends_at=None,
        )
        admin = build_player(
            telegram_id=100,
            display_name="Admin",
            status=UserStatus.ACTIVE,
            role=UserRole.ADMIN,
        )
        registered_no_show = build_player(
            telegram_id=101,
            display_name="No Show",
            status=UserStatus.ACTIVE,
        )
        registered_checked_in = build_player(
            telegram_id=102,
            display_name="Checked In",
            status=UserStatus.ACTIVE,
        )
        walk_in = build_player(
            telegram_id=None,
            display_name="Walk In",
            status=UserStatus.ACTIVE,
        )
        session.add_all([season, admin, registered_no_show, registered_checked_in, walk_in])
        await session.flush()
        tournament = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 7, 18),
            status=TournamentStatus.ACTIVE,
        )
        session.add(tournament)
        await session.flush()
        session.add_all(
            [
                TournamentRegistration(
                    tournament_id=tournament.id,
                    player_id=registered_no_show.id,
                    status=RegistrationStatus.REGISTERED,
                ),
                TournamentRegistration(
                    tournament_id=tournament.id,
                    player_id=registered_checked_in.id,
                    status=RegistrationStatus.REGISTERED,
                ),
                TournamentParticipant(
                    tournament_id=tournament.id,
                    user_id=registered_checked_in.id,
                    source=TournamentParticipantSource.PRE_REGISTERED,
                    checked_in_by_user_id=admin.id,
                ),
                TournamentParticipant(
                    tournament_id=tournament.id,
                    user_id=walk_in.id,
                    source=TournamentParticipantSource.DATABASE_WALK_IN,
                    checked_in_by_user_id=admin.id,
                ),
            ]
        )
        await session.commit()
        tournament_id = tournament.id
        expected_player_ids = [registered_checked_in.id, walk_in.id]

    service = ResultService(session_factory)
    draft = await service.get_or_create_draft(100, tournament_id)

    assert [player.player_id for player in draft.players] == expected_player_ids
    await engine.dispose()


async def test_admin_created_player_check_in_creates_offline_user_and_review(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'admin_created.db'}")
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
            ends_at=None,
        )
        admin = build_player(
            telegram_id=100,
            display_name="Admin",
            status=UserStatus.ACTIVE,
            role=UserRole.ADMIN,
        )
        session.add_all([season, admin])
        await session.flush()
        tournament = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 7, 18),
            status=TournamentStatus.ACTIVE,
        )
        session.add(tournament)
        await session.commit()
        tournament_id = tournament.id

    service = TournamentParticipantService(session_factory)
    view = await service.create_user_and_check_in(100, tournament_id, "  Новый   Игрок ")

    assert view.participant_count == 1
    assert view.walk_in_count == 1
    async with session_factory() as session:
        participant = (await session.execute(select(TournamentParticipant))).scalar_one()
        user = await session.get(User, participant.user_id)
        request = (await session.execute(select(RegistrationRequest))).scalar_one()
        draft = (await session.execute(select(TournamentResultDraft))).scalar_one()

    assert user is not None
    assert user.telegram_id is None
    assert user.display_name == "  Новый   Игрок "
    assert participant.source == TournamentParticipantSource.ADMIN_CREATED
    assert request.telegram_id is None
    assert request.subject_user_id == user.id
    assert request.tournament_id == tournament_id
    assert draft.player_id == user.id
    await engine.dispose()
