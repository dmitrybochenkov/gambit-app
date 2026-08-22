from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from conftest import seed_tournament_types_async, tournament_type_id
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.common.clock import FixedClock
from app.db.base import Base
from app.db.factories import create_user
from app.db.models import (
    RegistrationRequest,
    ScoringConfig,
    Season,
    Tournament,
    TournamentRegistration,
    User,
)
from app.db.models.enums import (
    RegistrationRequestStatus,
    RegistrationRequestType,
    TournamentStatus,
    UserRole,
    UserStatus,
)
from app.services.admin_management_service import AdminManagementService
from app.services.dto.users import UserStartStatusView
from app.services.registration_review_service import (
    RegistrationReviewService,
    TournamentRegistrationsUnavailableError,
)
from app.services.registration_service import RegistrationService
from app.services.user_access_service import UserAccessService
from app.services.user_common import (
    DisplayNameHistoricalUserExistsError,
    DisplayNameLinkedUserExistsError,
    IdentityAlreadyExistsError,
    RegistrationCandidateNotFoundError,
    RegistrationNotAllowedError,
    UserNotFoundError,
    UserRoleAlreadyAssignedError,
)


class UserLifecycleServices:
    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._services = (
            RegistrationService(session_factory),
            RegistrationReviewService(session_factory),
            UserAccessService(session_factory),
            AdminManagementService(session_factory),
        )

    def __getattr__(self, name: str) -> Any:
        for service in self._services:
            if hasattr(service, name):
                return getattr(service, name)
        raise AttributeError(name)


async def create_user_service(database_path: Path) -> tuple[UserLifecycleServices, object]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return UserLifecycleServices(async_sessionmaker(engine, expire_on_commit=False)), engine


@pytest.mark.asyncio
async def test_new_player_registration_creates_request_only(tmp_path: Path) -> None:
    service, engine = await create_user_service(tmp_path / "users.db")
    try:
        request = await service.submit_new_player_registration(telegram_id=1001, display_name="Ёж")

        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            users = (await session.execute(select(User))).scalars().all()
            stored_request = await session.get(RegistrationRequest, request.id)

        assert users == []
        assert stored_request is not None
        assert stored_request.request_type == RegistrationRequestType.NEW_PLAYER
        assert stored_request.status == RegistrationRequestStatus.PENDING
        assert stored_request.requested_display_name == "Ёж"
        assert stored_request.requested_display_name_normalized == "еж"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_new_player_registration_rejects_existing_display_name(tmp_path: Path) -> None:
    service, engine = await create_user_service(tmp_path / "users.db")
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add(create_user(display_name="Дима Боченков", telegram_id=1))
            await session.commit()

        with pytest.raises(IdentityAlreadyExistsError):
            await service.submit_new_player_registration(
                telegram_id=1001,
                display_name=" дима   боченков ",
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_registrations_overview_counts_only_active_tournament_registrations(
    tmp_path: Path,
) -> None:
    service, engine = await create_user_service(tmp_path / "registrations_overview.db")
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            config = ScoringConfig()
            session.add(config)
            await session.flush()
            await seed_tournament_types_async(session)
            season = Season(
                name="Лето 2026",
                scoring_config_id=config.id,
                starts_at=date(2026, 7, 1),
                ends_at=None,
            )
            superadmin = create_user(
                telegram_id=1,
                display_name="Superadmin",
                role=UserRole.SUPERADMIN,
                status=UserStatus.ACTIVE,
            )
            first = create_user(display_name="First", status=UserStatus.ACTIVE)
            second = create_user(display_name="Second", status=UserStatus.ACTIVE)
            session.add_all([season, superadmin, first, second])
            await session.flush()
            active = Tournament(
                season_id=season.id,
                tournament_type_id=tournament_type_id("bounty"),
                date=date(2026, 8, 19),
                status=TournamentStatus.ACTIVE,
            )
            closed = Tournament(
                season_id=season.id,
                tournament_type_id=tournament_type_id("classic"),
                date=date(2026, 8, 20),
                status=TournamentStatus.CLOSED,
                tournament_fund=1000,
            )
            session.add_all([active, closed])
            await session.flush()
            session.add_all(
                [
                    TournamentRegistration(tournament_id=active.id, player_id=first.id),
                    TournamentRegistration(tournament_id=active.id, player_id=second.id),
                    TournamentRegistration(tournament_id=closed.id, player_id=first.id),
                ]
            )
            await session.commit()

        review_service = RegistrationReviewService(
            async_sessionmaker(engine, expire_on_commit=False),
            clock=FixedClock(datetime(2026, 8, 19, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
            tournament_day_start_hour=11,
        )
        overview = await review_service.get_registrations_overview_for_superadmin(1)

        assert overview.pending_user_registration_count == 0
        assert overview.active_tournament_registration_count == 2
        assert [
            (item.tournament_type_name, item.registrations_count) for item in overview.tournaments
        ] == [("Баунти турнир", 2)]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_tournament_registrations_detail_uses_registration_rows_and_player_order(
    tmp_path: Path,
) -> None:
    _, engine = await create_user_service(tmp_path / "registrations_detail.db")
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            config = ScoringConfig()
            session.add(config)
            await session.flush()
            await seed_tournament_types_async(session)
            season = Season(
                name="Лето 2026",
                scoring_config_id=config.id,
                starts_at=date(2026, 7, 1),
                ends_at=None,
            )
            superadmin = create_user(
                telegram_id=1,
                display_name="Superadmin",
                role=UserRole.SUPERADMIN,
                status=UserStatus.ACTIVE,
            )
            alpha = create_user(display_name="Алексей", status=UserStatus.ACTIVE)
            beta = create_user(display_name="Борис", status=UserStatus.ACTIVE)
            session.add_all([season, superadmin, beta, alpha])
            await session.flush()
            tournament = Tournament(
                season_id=season.id,
                tournament_type_id=tournament_type_id("double_double"),
                date=date(2026, 8, 22),
                status=TournamentStatus.ACTIVE,
            )
            session.add(tournament)
            await session.flush()
            session.add_all(
                [
                    TournamentRegistration(tournament_id=tournament.id, player_id=beta.id),
                    TournamentRegistration(tournament_id=tournament.id, player_id=alpha.id),
                ]
            )
            tournament_id = tournament.id
            await session.commit()

        review_service = RegistrationReviewService(
            async_sessionmaker(engine, expire_on_commit=False),
            clock=FixedClock(datetime(2026, 8, 22, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
            tournament_day_start_hour=11,
        )
        detail = await review_service.get_tournament_registrations_detail_for_superadmin(
            1,
            tournament_id,
        )

        assert detail.date == date(2026, 8, 22)
        assert detail.tournament_type_name == "Double Double"
        assert [player.display_name for player in detail.players] == ["Алексей", "Борис"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_tournament_registrations_detail_rejects_unavailable_tournament(
    tmp_path: Path,
) -> None:
    _, engine = await create_user_service(tmp_path / "registrations_detail_stale.db")
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            config = ScoringConfig()
            session.add(config)
            await session.flush()
            await seed_tournament_types_async(session)
            season = Season(
                name="Лето 2026",
                scoring_config_id=config.id,
                starts_at=date(2026, 7, 1),
                ends_at=None,
            )
            superadmin = create_user(
                telegram_id=1,
                display_name="Superadmin",
                role=UserRole.SUPERADMIN,
                status=UserStatus.ACTIVE,
            )
            player = create_user(display_name="Игрок", status=UserStatus.ACTIVE)
            session.add_all([season, superadmin, player])
            await session.flush()
            closed = Tournament(
                season_id=season.id,
                tournament_type_id=tournament_type_id("classic"),
                date=date(2026, 8, 22),
                status=TournamentStatus.CLOSED,
                tournament_fund=1000,
            )
            empty = Tournament(
                season_id=season.id,
                tournament_type_id=tournament_type_id("bounty"),
                date=date(2026, 8, 23),
                status=TournamentStatus.ACTIVE,
            )
            session.add_all([closed, empty])
            await session.flush()
            session.add(TournamentRegistration(tournament_id=closed.id, player_id=player.id))
            closed_id = closed.id
            empty_id = empty.id
            await session.commit()

        review_service = RegistrationReviewService(
            async_sessionmaker(engine, expire_on_commit=False),
            clock=FixedClock(datetime(2026, 8, 22, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
            tournament_day_start_hour=11,
        )
        with pytest.raises(TournamentRegistrationsUnavailableError):
            await review_service.get_tournament_registrations_detail_for_superadmin(1, closed_id)
        with pytest.raises(TournamentRegistrationsUnavailableError):
            await review_service.get_tournament_registrations_detail_for_superadmin(1, empty_id)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_registrations_overview_uses_tournament_day_boundary(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'overview_day.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            config = ScoringConfig()
            session.add(config)
            await session.flush()
            await seed_tournament_types_async(session)
            season = Season(
                name="Лето 2026",
                scoring_config_id=config.id,
                starts_at=date(2026, 8, 1),
                ends_at=None,
            )
            superadmin = create_user(
                telegram_id=1,
                display_name="Superadmin",
                role=UserRole.SUPERADMIN,
                status=UserStatus.ACTIVE,
            )
            players = [
                create_user(display_name=f"Player {index}", status=UserStatus.ACTIVE)
                for index in range(1, 6)
            ]
            session.add_all([season, superadmin, *players])
            await session.flush()
            past_active = Tournament(
                season_id=season.id,
                tournament_type_id=tournament_type_id("classic"),
                date=date(2026, 8, 18),
                status=TournamentStatus.ACTIVE,
            )
            previous_game_day = Tournament(
                season_id=season.id,
                tournament_type_id=tournament_type_id("bounty"),
                date=date(2026, 8, 19),
                status=TournamentStatus.ACTIVE,
            )
            future_active = Tournament(
                season_id=season.id,
                tournament_type_id=tournament_type_id("freezeout"),
                date=date(2026, 8, 21),
                status=TournamentStatus.ACTIVE,
            )
            closed_future = Tournament(
                season_id=season.id,
                tournament_type_id=tournament_type_id("classic"),
                date=date(2026, 8, 22),
                status=TournamentStatus.CLOSED,
                tournament_fund=1000,
            )
            session.add_all([past_active, previous_game_day, future_active, closed_future])
            await session.flush()
            session.add_all(
                [
                    TournamentRegistration(tournament_id=past_active.id, player_id=players[0].id),
                    TournamentRegistration(
                        tournament_id=previous_game_day.id,
                        player_id=players[1].id,
                    ),
                    TournamentRegistration(
                        tournament_id=future_active.id,
                        player_id=players[2].id,
                    ),
                    TournamentRegistration(tournament_id=closed_future.id, player_id=players[3].id),
                ]
            )
            await session.commit()

        before_start = RegistrationReviewService(
            session_factory,
            clock=FixedClock(datetime(2026, 8, 20, 10, 59, tzinfo=ZoneInfo("Europe/Moscow"))),
            tournament_day_start_hour=11,
        )
        at_start = RegistrationReviewService(
            session_factory,
            clock=FixedClock(datetime(2026, 8, 20, 11, 0, tzinfo=ZoneInfo("Europe/Moscow"))),
            tournament_day_start_hour=11,
        )
        after_all = RegistrationReviewService(
            session_factory,
            clock=FixedClock(datetime(2026, 8, 23, 11, 0, tzinfo=ZoneInfo("Europe/Moscow"))),
            tournament_day_start_hour=11,
        )

        before_overview = await before_start.get_registrations_overview_for_superadmin(1)
        at_start_overview = await at_start.get_registrations_overview_for_superadmin(1)
        empty_overview = await after_all.get_registrations_overview_for_superadmin(1)

        assert [
            (item.date, item.tournament_type_name, item.registrations_count)
            for item in before_overview.tournaments
        ] == [
            (date(2026, 8, 19), "Баунти турнир", 1),
            (date(2026, 8, 21), "Фризаут", 1),
        ]
        assert before_overview.active_tournament_registration_count == 2
        assert before_overview.has_tournament_registrations is True

        assert [
            (item.date, item.tournament_type_name, item.registrations_count)
            for item in at_start_overview.tournaments
        ] == [(date(2026, 8, 21), "Фризаут", 1)]
        assert at_start_overview.active_tournament_registration_count == 1
        assert at_start_overview.has_tournament_registrations is True

        assert empty_overview.tournaments == []
        assert empty_overview.active_tournament_registration_count == 0
        assert empty_overview.has_tournament_registrations is False
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_new_player_registration_rejects_linked_display_name(
    tmp_path: Path,
) -> None:
    service, engine = await create_user_service(tmp_path / "users.db")
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add(create_user(display_name="Antony Easy", telegram_id=1))
            await session.commit()

        with pytest.raises(DisplayNameLinkedUserExistsError):
            await service.validate_new_player_display_name(" antony   easy ")
        with pytest.raises(DisplayNameLinkedUserExistsError):
            await service.submit_new_player_registration(1001, "Antony Easy")
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_new_player_registration_rejects_historical_display_name(
    tmp_path: Path,
) -> None:
    service, engine = await create_user_service(tmp_path / "users.db")
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add(create_user(display_name="Antony Easy"))
            await session.commit()

        with pytest.raises(DisplayNameHistoricalUserExistsError):
            await service.validate_new_player_display_name(" antony   easy ")
        with pytest.raises(DisplayNameHistoricalUserExistsError):
            await service.submit_new_player_registration(1001, "Antony Easy")
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_database_allows_duplicate_display_name_normalized(tmp_path: Path) -> None:
    _, engine = await create_user_service(tmp_path / "users.db")
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add(create_user(display_name="Журавлев Антон"))
            session.add(create_user(display_name="Журавлёв Антон"))
            await session.commit()

        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            users = (await session.execute(select(User).order_by(User.id))).scalars().all()

        assert [user.display_name_normalized for user in users] == [
            "журавлев антон",
            "журавлев антон",
        ]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_link_registration_requires_matching_historical_player(tmp_path: Path) -> None:
    service, engine = await create_user_service(tmp_path / "users.db")
    try:
        with pytest.raises(RegistrationCandidateNotFoundError):
            await service.submit_link_existing_registration(
                telegram_id=1001,
                requested_link_name="Нет такого",
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_approve_new_player_registration_creates_active_player(tmp_path: Path) -> None:
    service, engine = await create_user_service(tmp_path / "users.db")
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add(
                create_user(
                    display_name="Супер Админ",
                    telegram_id=1,
                    role=UserRole.SUPERADMIN,
                )
            )
            await session.commit()

        request = await service.submit_new_player_registration(telegram_id=1001, display_name="Ace")
        result = await service.approve_registration(
            superadmin_telegram_id=1,
            request_id=request.id,
        )

        assert result.user is not None
        assert result.user.display_name == "Ace"
        assert result.user.telegram_id == 1001
        assert result.user.role == UserRole.PLAYER
        assert result.request.status == RegistrationRequestStatus.APPROVED.value
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_registration_notification_recipients_are_active_superadmins_with_telegram(
    tmp_path: Path,
) -> None:
    service, engine = await create_user_service(tmp_path / "users.db")
    try:
        request = await service.submit_new_player_registration(telegram_id=1001, display_name="Ace")
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add_all(
                [
                    create_user(
                        display_name="Actor Superadmin",
                        telegram_id=1,
                        role=UserRole.SUPERADMIN,
                    ),
                    create_user(
                        display_name="Other Superadmin",
                        telegram_id=2,
                        role=UserRole.SUPERADMIN,
                    ),
                    create_user(
                        display_name="Regular Admin",
                        telegram_id=3,
                        role=UserRole.ADMIN,
                    ),
                    create_user(
                        display_name="Blocked Superadmin",
                        telegram_id=4,
                        role=UserRole.SUPERADMIN,
                        status=UserStatus.BLOCKED,
                    ),
                    create_user(
                        display_name="No Telegram Superadmin",
                        role=UserRole.SUPERADMIN,
                    ),
                ]
            )
            await session.commit()

        notification = await service.get_registration_notification(request.id)

        assert [(admin.telegram_id, admin.role, admin.status) for admin in notification.admins] == [
            (1, UserRole.SUPERADMIN, UserStatus.ACTIVE),
            (2, UserRole.SUPERADMIN, UserStatus.ACTIVE),
        ]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_approve_registration_review_recipients_are_active_superadmins_with_telegram(
    tmp_path: Path,
) -> None:
    service, engine = await create_user_service(tmp_path / "users.db")
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add_all(
                [
                    create_user(
                        display_name="Actor Superadmin",
                        telegram_id=1,
                        role=UserRole.SUPERADMIN,
                    ),
                    create_user(
                        display_name="Other Superadmin",
                        telegram_id=2,
                        role=UserRole.SUPERADMIN,
                    ),
                    create_user(
                        display_name="Regular Admin",
                        telegram_id=3,
                        role=UserRole.ADMIN,
                    ),
                    create_user(
                        display_name="Blocked Superadmin",
                        telegram_id=4,
                        role=UserRole.SUPERADMIN,
                        status=UserStatus.BLOCKED,
                    ),
                    create_user(
                        display_name="No Telegram Superadmin",
                        role=UserRole.SUPERADMIN,
                    ),
                ]
            )
            await session.commit()

        request = await service.submit_new_player_registration(telegram_id=1001, display_name="Ace")
        result = await service.approve_registration(
            superadmin_telegram_id=1,
            request_id=request.id,
        )

        assert [(admin.telegram_id, admin.role, admin.status) for admin in result.admins] == [
            (1, UserRole.SUPERADMIN, UserStatus.ACTIVE),
            (2, UserRole.SUPERADMIN, UserStatus.ACTIVE),
        ]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reject_registration_review_recipients_are_active_superadmins_with_telegram(
    tmp_path: Path,
) -> None:
    service, engine = await create_user_service(tmp_path / "users.db")
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add_all(
                [
                    create_user(
                        display_name="Actor Superadmin",
                        telegram_id=1,
                        role=UserRole.SUPERADMIN,
                    ),
                    create_user(
                        display_name="Other Superadmin",
                        telegram_id=2,
                        role=UserRole.SUPERADMIN,
                    ),
                    create_user(
                        display_name="Regular Admin",
                        telegram_id=3,
                        role=UserRole.ADMIN,
                    ),
                    create_user(
                        display_name="Blocked Superadmin",
                        telegram_id=4,
                        role=UserRole.SUPERADMIN,
                        status=UserStatus.BLOCKED,
                    ),
                    create_user(
                        display_name="No Telegram Superadmin",
                        role=UserRole.SUPERADMIN,
                    ),
                ]
            )
            await session.commit()

        request = await service.submit_new_player_registration(telegram_id=1001, display_name="Ace")
        result = await service.reject_registration(
            superadmin_telegram_id=1,
            request_id=request.id,
        )

        assert [(admin.telegram_id, admin.role, admin.status) for admin in result.admins] == [
            (1, UserRole.SUPERADMIN, UserStatus.ACTIVE),
            (2, UserRole.SUPERADMIN, UserStatus.ACTIVE),
        ]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_approve_new_player_registration_rechecks_display_name_conflict(
    tmp_path: Path,
) -> None:
    service, engine = await create_user_service(tmp_path / "users.db")
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add(
                create_user(
                    display_name="Супер Админ",
                    telegram_id=1,
                    role=UserRole.SUPERADMIN,
                )
            )
            await session.commit()

        request = await service.submit_new_player_registration(telegram_id=1001, display_name="Ace")
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add(create_user(display_name="Ace", telegram_id=2002))
            await session.commit()

        with pytest.raises(DisplayNameLinkedUserExistsError):
            await service.approve_registration(
                superadmin_telegram_id=1,
                request_id=request.id,
            )

        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            stored_request = await session.get(RegistrationRequest, request.id)
            users = (
                (await session.execute(select(User).where(User.display_name == "Ace")))
                .scalars()
                .all()
            )

        assert stored_request is not None
        assert stored_request.status == RegistrationRequestStatus.PENDING
        assert len(users) == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_registration_notification_recipients_are_active_superadmins_only(
    tmp_path: Path,
) -> None:
    service, engine = await create_user_service(tmp_path / "users.db")
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add(
                create_user(
                    display_name="Супер Админ",
                    telegram_id=1,
                    role=UserRole.SUPERADMIN,
                )
            )
            session.add(
                create_user(
                    display_name="Обычный Админ",
                    telegram_id=2,
                    role=UserRole.ADMIN,
                )
            )
            session.add(
                create_user(
                    display_name="Оффлайн Супер",
                    role=UserRole.SUPERADMIN,
                )
            )
            session.add(create_user(display_name="Игрок", telegram_id=3))
            request = RegistrationRequest(
                telegram_id=1001,
                request_type=RegistrationRequestType.NEW_PLAYER,
                status=RegistrationRequestStatus.PENDING,
                requested_display_name="Новый Игрок",
                requested_display_name_normalized="новый игрок",
            )
            session.add(request)
            await session.commit()
            request_id = request.id

        notification = await service.get_registration_notification(request_id)

        assert [admin.display_name for admin in notification.admins] == ["Супер Админ"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_approve_link_registration_attaches_telegram_id(tmp_path: Path) -> None:
    service, engine = await create_user_service(tmp_path / "users.db")
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add(
                create_user(
                    display_name="Супер Админ",
                    telegram_id=1,
                    role=UserRole.SUPERADMIN,
                )
            )
            session.add(create_user(display_name="Исторический Игрок"))
            await session.commit()

        request = await service.submit_link_existing_registration(
            telegram_id=1001,
            requested_link_name="Исторический",
        )
        review = await service.get_registration_review_for_admin(1, request.id)
        result = await service.select_registration_candidate(
            superadmin_telegram_id=1,
            request_id=request.id,
            user_id=review.candidates[0].user.id,
        )
        approved = await service.approve_registration(
            superadmin_telegram_id=1,
            request_id=result.request.id,
        )

        assert approved.user is not None
        assert approved.user.display_name == "Исторический Игрок"
        assert approved.user.telegram_id == 1001
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_link_registration_returns_multiple_duplicate_name_candidates(
    tmp_path: Path,
) -> None:
    service, engine = await create_user_service(tmp_path / "users.db")
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add(
                create_user(
                    display_name="Супер Админ",
                    telegram_id=1,
                    role=UserRole.SUPERADMIN,
                )
            )
            session.add(create_user(display_name="Husband"))
            session.add(create_user(display_name="husband"))
            await session.commit()

        request = await service.submit_link_existing_registration(
            telegram_id=1001,
            requested_link_name="Husband",
        )
        review = await service.get_registration_review_for_admin(1, request.id)

        assert [candidate.user.display_name for candidate in review.candidates] == [
            "Husband",
            "husband",
        ]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_link_registration_approves_selected_user_id(tmp_path: Path) -> None:
    service, engine = await create_user_service(tmp_path / "users.db")
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add(
                create_user(
                    display_name="Супер Админ",
                    telegram_id=1,
                    role=UserRole.SUPERADMIN,
                )
            )
            first = create_user(display_name="Журавлев Антон")
            second = create_user(display_name="Журавлёв Антон")
            session.add_all([first, second])
            await session.commit()
            selected_id = second.id

        request = await service.submit_link_existing_registration(
            telegram_id=1001,
            requested_link_name="Журавлев Антон",
        )
        review = await service.select_registration_candidate(1, request.id, selected_id)
        approved = await service.approve_registration(1, request.id, candidate_user_id=selected_id)

        assert review.selected_candidate is not None
        assert review.selected_candidate.user.id == selected_id
        assert approved.user is not None
        assert approved.user.id == selected_id
        assert approved.user.display_name == "Журавлёв Антон"
        assert approved.user.telegram_id == 1001
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_link_registration_candidate_selection_does_not_mutate_request(
    tmp_path: Path,
) -> None:
    service, engine = await create_user_service(tmp_path / "users.db")
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add(
                create_user(
                    display_name="Супер Админ",
                    telegram_id=1,
                    role=UserRole.SUPERADMIN,
                )
            )
            candidate = create_user(display_name="Исторический Игрок")
            session.add(candidate)
            await session.commit()
            candidate_id = candidate.id

        request = await service.submit_link_existing_registration(1001, "Исторический")
        review = await service.select_registration_candidate(1, request.id, candidate_id)

        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            stored_request = await session.get(RegistrationRequest, request.id)
            stored_candidate = await session.get(User, candidate_id)

        assert review.selected_candidate is not None
        assert review.selected_candidate.user.id == candidate_id
        assert stored_request is not None
        assert stored_request.candidate_user_id is None
        assert stored_candidate is not None
        assert stored_candidate.telegram_id is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_link_registration_confirmation_rejects_stale_candidate(
    tmp_path: Path,
) -> None:
    service, engine = await create_user_service(tmp_path / "users.db")
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add(
                create_user(
                    display_name="Супер Админ",
                    telegram_id=1,
                    role=UserRole.SUPERADMIN,
                )
            )
            candidate = create_user(display_name="Исторический Игрок")
            session.add(candidate)
            await session.commit()
            candidate_id = candidate.id

        request = await service.submit_link_existing_registration(1001, "Исторический")
        await service.select_registration_candidate(1, request.id, candidate_id)
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            stored_candidate = await session.get(User, candidate_id)
            assert stored_candidate is not None
            stored_candidate.telegram_id = 2002
            await session.commit()

        with pytest.raises(RegistrationCandidateNotFoundError):
            await service.approve_registration(
                1,
                request.id,
                candidate_user_id=candidate_id,
            )

        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            stored_request = await session.get(RegistrationRequest, request.id)
            stored_candidate = await session.get(User, candidate_id)

        assert stored_request is not None
        assert stored_request.status == RegistrationRequestStatus.PENDING
        assert stored_candidate is not None
        assert stored_candidate.telegram_id == 2002
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_link_registration_does_not_offer_already_linked_user(tmp_path: Path) -> None:
    service, engine = await create_user_service(tmp_path / "users.db")
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add(
                create_user(
                    display_name="Супер Админ",
                    telegram_id=1,
                    role=UserRole.SUPERADMIN,
                )
            )
            session.add(create_user(display_name="Husband", telegram_id=2001))
            session.add(create_user(display_name="husband"))
            await session.commit()

        request = await service.submit_link_existing_registration(
            telegram_id=1001,
            requested_link_name="Husband",
        )
        review = await service.get_registration_review_for_admin(1, request.id)

        assert [candidate.user.display_name for candidate in review.candidates] == ["husband"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_same_telegram_cannot_be_linked_to_multiple_users(tmp_path: Path) -> None:
    service, engine = await create_user_service(tmp_path / "users.db")
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add(
                create_user(
                    display_name="Супер Админ",
                    telegram_id=1,
                    role=UserRole.SUPERADMIN,
                )
            )
            first = create_user(display_name="Первый Игрок")
            second = create_user(display_name="Второй Игрок")
            session.add_all([first, second])
            await session.commit()
            first_id = first.id
            second_id = second.id

        first_request = await service.submit_link_existing_registration(1001, "Первый")
        await service.select_registration_candidate(1, first_request.id, first_id)
        await service.approve_registration(1, first_request.id)

        second_request = await service.submit_link_existing_registration(1002, "Второй")
        await service.select_registration_candidate(1, second_request.id, second_id)
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            stored_request = await session.get(RegistrationRequest, second_request.id)
            assert stored_request is not None
            stored_request.telegram_id = 1001
            await session.commit()

        with pytest.raises(RegistrationNotAllowedError):
            await service.approve_registration(1, second_request.id)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_existing_telegram_user_cannot_register_again(tmp_path: Path) -> None:
    service, engine = await create_user_service(tmp_path / "users.db")
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add(create_user(display_name="Ace", telegram_id=1001))
            await session.commit()

        with pytest.raises(RegistrationNotAllowedError):
            await service.submit_new_player_registration(telegram_id=1001, display_name="Ace 2")
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_start_view_reports_existing_active_user(tmp_path: Path) -> None:
    service, engine = await create_user_service(tmp_path / "users.db")
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add(
                create_user(
                    display_name="Супер Админ",
                    telegram_id=1,
                    role=UserRole.SUPERADMIN,
                )
            )
            await session.commit()

        start_view = await service.get_start_view(1)

        assert start_view.status == UserStartStatusView.REGISTERED
        assert start_view.user is not None
        assert start_view.user.display_name == "Супер Админ"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_start_view_reports_pending_registration(tmp_path: Path) -> None:
    service, engine = await create_user_service(tmp_path / "users.db")
    try:
        await service.submit_new_player_registration(telegram_id=1001, display_name="Ace")

        start_view = await service.get_start_view(1001)

        assert start_view.status == UserStartStatusView.PENDING_REGISTRATION
        assert start_view.user is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_admin_candidate_search_only_returns_active_linked_players(
    tmp_path: Path,
) -> None:
    service, engine = await create_user_service(tmp_path / "users.db")
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add(
                create_user(
                    display_name="Супер Админ",
                    telegram_id=1,
                    role=UserRole.SUPERADMIN,
                )
            )
            session.add(create_user(display_name="Antony Easy", telegram_id=1001))
            session.add(create_user(display_name="Antony Offline"))
            session.add(
                create_user(
                    display_name="Antony Blocked",
                    telegram_id=1002,
                    status=UserStatus.BLOCKED,
                )
            )
            session.add(
                create_user(
                    display_name="Antony Admin",
                    telegram_id=1003,
                    role=UserRole.ADMIN,
                )
            )
            session.add(
                create_user(
                    display_name="Antony Super",
                    telegram_id=1004,
                    role=UserRole.SUPERADMIN,
                )
            )
            await session.commit()

        candidates = await service.search_admin_candidates_for_superadmin(1, "Antony")

        assert [candidate.display_name for candidate in candidates] == ["Antony Easy"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_add_admin_requires_active_linked_player(tmp_path: Path) -> None:
    service, engine = await create_user_service(tmp_path / "users.db")
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add(
                create_user(
                    display_name="Супер Админ",
                    telegram_id=1,
                    role=UserRole.SUPERADMIN,
                )
            )
            offline = create_user(display_name="Offline")
            blocked = create_user(
                display_name="Blocked",
                telegram_id=1002,
                status=UserStatus.BLOCKED,
            )
            admin = create_user(
                display_name="Admin",
                telegram_id=1003,
                role=UserRole.ADMIN,
            )
            player = create_user(display_name="Player", telegram_id=1004)
            session.add_all([offline, blocked, admin, player])
            await session.commit()
            offline_id = offline.id
            blocked_id = blocked.id
            admin_id = admin.id
            player_id = player.id

        with pytest.raises(UserNotFoundError):
            await service.add_admin(1, offline_id)
        with pytest.raises(UserNotFoundError):
            await service.add_admin(1, blocked_id)
        with pytest.raises(UserRoleAlreadyAssignedError):
            await service.add_admin(1, admin_id)

        promoted = await service.add_admin(1, player_id)

        assert promoted.role == UserRole.ADMIN
    finally:
        await engine.dispose()
