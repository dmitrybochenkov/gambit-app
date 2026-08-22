from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from conftest import (
    build_player,
    seed_tournament_configs_async,
    seed_tournament_types_async,
    tournament_type_id,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.common.clock import FixedClock
from app.db.base import Base
from app.db.models import ScoringConfig, Season, Tournament, TournamentEconomyConfig
from app.db.models.enums import TournamentStatus, UserRole, UserStatus
from app.services.tournament_publication_service import TournamentPublicationService


async def test_schedule_publication_uses_detail_dto_and_hash_changes_with_economy(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'publication.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        config = ScoringConfig()
        session.add(config)
        await session.flush()
        await seed_tournament_types_async(session)
        await seed_tournament_configs_async(session)
        season = Season(
            name="Test season",
            scoring_config_id=config.id,
            starts_at=date(2026, 8, 1),
            ends_at=None,
        )
        superadmin = build_player(
            telegram_id=100,
            display_name="Superadmin",
            status=UserStatus.ACTIVE,
            role=UserRole.SUPERADMIN,
        )
        session.add_all([season, superadmin])
        await session.flush()
        tournament = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 8, 26),
            status=TournamentStatus.ACTIVE,
        )
        session.add(tournament)
        await session.commit()

    service = TournamentPublicationService(
        session_factory,
        clock=FixedClock(datetime(2026, 8, 22, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
        club_chat_id=-100,
        club_channel_id=-200,
    )
    first = await service.get_schedule_publication_preview(100)

    assert len(first.tournaments) == 1
    assert first.tournaments[0].tournament_type_name == "Классика"
    assert first.tournaments[0].economy is not None
    assert first.tournaments[0].economy.entry_stack == 20_000
    assert [destination.chat_id for destination in first.destinations] == [-100, -200]

    async with session_factory() as session:
        economy = (
            await session.execute(
                select(TournamentEconomyConfig).where(
                    TournamentEconomyConfig.tournament_type_id == tournament_type_id("classic")
                )
            )
        ).scalar_one()
        economy.entry_stack = 25_000
        await session.commit()

    second = await service.get_schedule_publication_preview(100)

    assert second.tournaments[0].economy is not None
    assert second.tournaments[0].economy.entry_stack == 25_000
    assert second.content_hash != first.content_hash
    await engine.dispose()
