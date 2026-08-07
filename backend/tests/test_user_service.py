from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.factories import create_user
from app.db.models import RegistrationRequest, User
from app.db.models.enums import (
    RegistrationRequestStatus,
    RegistrationRequestType,
    UserRole,
)
from app.services.admin_management_service import AdminManagementService
from app.services.dto.users import UserStartStatusView
from app.services.registration_review_service import RegistrationReviewService
from app.services.registration_service import RegistrationService
from app.services.user_access_service import UserAccessService
from app.services.user_common import (
    IdentityAlreadyExistsError,
    RegistrationCandidateNotFoundError,
    RegistrationNotAllowedError,
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
        await service.select_registration_candidate(1, request.id, selected_id)
        approved = await service.approve_registration(1, request.id)

        assert approved.user is not None
        assert approved.user.id == selected_id
        assert approved.user.display_name == "Журавлёв Антон"
        assert approved.user.telegram_id == 1001
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
