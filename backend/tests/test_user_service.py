from pathlib import Path

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
from app.services.dto import UserRoleView
from app.services.user_service import (
    IdentityAlreadyExistsError,
    RegistrationCandidateNotFoundError,
    RegistrationNotAllowedError,
    UserService,
)


async def create_user_service(database_path: Path) -> tuple[UserService, object]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return UserService(async_sessionmaker(engine, expire_on_commit=False)), engine


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
        assert result.user.role == UserRoleView.PLAYER
        assert result.request.status == RegistrationRequestStatus.APPROVED.value
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
