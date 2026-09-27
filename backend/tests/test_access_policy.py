import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import User
from app.db.models.enums import UserRole, UserStatus
from app.services.access_policy import (
    AccessPolicy,
    ActiveUserRequiredError,
    AdminAccessDeniedError,
)
from app.services.profile_service import ProfileKind, ProfileService


@pytest.fixture
async def access_policy_data(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'access-policy.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        session.add_all(
            [
                User(
                    id=101,
                    telegram_id=202,
                    display_name="Player",
                    display_name_normalized="player",
                    role=UserRole.PLAYER,
                    status=UserStatus.ACTIVE,
                ),
                User(
                    id=202,
                    telegram_id=303,
                    display_name="Admin",
                    display_name_normalized="admin",
                    role=UserRole.ADMIN,
                    status=UserStatus.ACTIVE,
                ),
                User(
                    id=303,
                    telegram_id=404,
                    display_name="Superadmin",
                    display_name_normalized="superadmin",
                    role=UserRole.SUPERADMIN,
                    status=UserStatus.ACTIVE,
                ),
                User(
                    id=404,
                    telegram_id=505,
                    display_name="Blocked",
                    display_name_normalized="blocked",
                    role=UserRole.SUPERADMIN,
                    status=UserStatus.BLOCKED,
                ),
            ]
        )
        await session.commit()

    yield session_factory
    await engine.dispose()


async def test_neutral_policy_uses_internal_user_id_namespace(access_policy_data) -> None:
    async with access_policy_data() as session:
        player = await AccessPolicy().require_active_user(session, 101)
        admin = await AccessPolicy().require_active_user(session, 202)

    assert player.id == 101
    assert player.telegram_id == 202
    assert admin.id == 202
    assert admin.telegram_id == 303


async def test_telegram_compatibility_policy_uses_telegram_id_namespace(
    access_policy_data,
) -> None:
    async with access_policy_data() as session:
        player = await AccessPolicy().require_active_user_by_telegram_id(session, 202)

    assert player.id == 101
    assert player.telegram_id == 202


async def test_neutral_and_telegram_role_checks_share_existing_semantics(
    access_policy_data,
) -> None:
    policy = AccessPolicy()
    async with access_policy_data() as session:
        assert (await policy.require_admin(session, 202)).role == UserRole.ADMIN
        assert (await policy.require_admin(session, 303)).role == UserRole.SUPERADMIN
        assert (await policy.require_superadmin(session, 303)).role == UserRole.SUPERADMIN
        assert (await policy.require_admin_by_telegram_id(session, 303)).role == UserRole.ADMIN
        assert (
            await policy.require_superadmin_by_telegram_id(session, 404)
        ).role == UserRole.SUPERADMIN

        with pytest.raises(AdminAccessDeniedError):
            await policy.require_admin(session, 101)
        with pytest.raises(AdminAccessDeniedError):
            await policy.require_superadmin_by_telegram_id(session, 303)


@pytest.mark.parametrize(
    ("method_name", "actor_id"),
    [
        ("require_active_user", 404),
        ("require_active_user", 999),
        ("require_active_user_by_telegram_id", 505),
        ("require_active_user_by_telegram_id", 999),
    ],
)
async def test_neutral_and_telegram_policy_reject_blocked_or_missing_users(
    access_policy_data,
    method_name: str,
    actor_id: int,
) -> None:
    policy = AccessPolicy()
    async with access_policy_data() as session:
        with pytest.raises(ActiveUserRequiredError):
            await getattr(policy, method_name)(session, actor_id)


async def test_profile_service_treats_actor_value_only_as_internal_user_id(
    access_policy_data,
) -> None:
    service = ProfileService(access_policy_data)

    _, internal_actor_profile = await service.get_profile_for_player(
        actor_user_id=101,
        kind=ProfileKind.ALL_TIME,
    )
    _, colliding_actor_profile = await service.get_profile_for_player(
        actor_user_id=202,
        kind=ProfileKind.ALL_TIME,
    )

    assert internal_actor_profile is not None
    assert internal_actor_profile.display_name == "Player"
    assert colliding_actor_profile is not None
    assert colliding_actor_profile.display_name == "Admin"
