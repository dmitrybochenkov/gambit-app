import hashlib
import hmac
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import admin_management_dependencies, dependencies
from app.api.admin_management_dependencies import admin_promotion_notification_delivery
from app.api.v1 import admin_users
from app.bot.telegram import runtime
from app.db.base import Base
from app.db.factories import create_user
from app.db.models import User
from app.db.models.enums import UserGender, UserRole, UserStatus
from app.main import app
from app.services.admin_management_service import AdminManagementService
from app.services.admin_management_use_cases import AdminManagementUseCases
from app.services.dto.users import UserView
from app.services.user_access_service import UserAccessService
from app.services.user_rename_service import UserRenameService

TEST_BOT_TOKEN = "123456:test-token"


def signed_init_data(telegram_id: int) -> str:
    data = {
        "auth_date": str(int(datetime.now(UTC).timestamp())),
        "query_id": "admin-users-api-test",
        "user": json.dumps(
            {"id": telegram_id, "first_name": "Test"},
            separators=(",", ":"),
        ),
    }
    data_check_string = "\n".join(f"{key}={data[key]}" for key in sorted(data))
    secret_key = hmac.new(b"WebAppData", TEST_BOT_TOKEN.encode(), hashlib.sha256).digest()
    data["hash"] = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(data)


def auth_headers(telegram_id: int) -> dict[str, str]:
    return {"Authorization": f"tma {signed_init_data(telegram_id)}"}


class RecordingPromotionDelivery:
    def __init__(self) -> None:
        self.users: list[UserView] = []
        self.fail = False

    async def deliver(self, promoted_user: UserView) -> None:
        self.users.append(promoted_user)
        if self.fail:
            raise RuntimeError("delivery unavailable")


def test_admin_promotion_delivery_dependency_reads_runtime_bot_at_call_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_bot = object()
    monkeypatch.setattr(runtime, "telegram_bot", current_bot)

    delivery = admin_management_dependencies.admin_promotion_notification_delivery()

    assert getattr(delivery, "_bot") is current_bot


@pytest.fixture
async def admin_users_api(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[
    tuple[AsyncClient, async_sessionmaker, RecordingPromotionDelivery, dict[str, int]]
]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'admin-users.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    admin_service = AdminManagementService(session_factory)
    rename_service = UserRenameService(session_factory)
    delivery = RecordingPromotionDelivery()

    monkeypatch.setattr(dependencies.settings, "telegram_bot_token", TEST_BOT_TOKEN)
    monkeypatch.setattr(dependencies.settings, "telegram_webapp_auth_max_age_seconds", 60)
    monkeypatch.setattr(dependencies, "user_access_service", UserAccessService(session_factory))
    monkeypatch.setattr(admin_users, "admin_management_service", admin_service)
    monkeypatch.setattr(admin_users, "user_rename_service", rename_service)
    monkeypatch.setattr(
        admin_users,
        "admin_management_use_cases",
        AdminManagementUseCases(admin_service),
    )
    app.dependency_overrides[admin_promotion_notification_delivery] = lambda: delivery

    async with session_factory() as session:
        root = create_user(
            display_name="Root Superadmin",
            telegram_id=200,
            role=UserRole.SUPERADMIN,
        )
        other_superadmin = create_user(
            display_name="Other Superadmin",
            telegram_id=201,
            role=UserRole.SUPERADMIN,
        )
        admin = create_user(display_name="Existing Admin", telegram_id=100, role=UserRole.ADMIN)
        player_actor = create_user(display_name="Player Actor", telegram_id=300)
        candidate = create_user(display_name="Candidate Player", telegram_id=400)
        offline = create_user(display_name="Offline Player")
        blocked = create_user(
            display_name="Blocked Player",
            telegram_id=500,
            status=UserStatus.BLOCKED,
        )
        session.add_all([root, other_superadmin, admin, player_actor, candidate, offline, blocked])
        await session.commit()
        ids = {
            "root": root.id,
            "other_superadmin": other_superadmin.id,
            "admin": admin.id,
            "player_actor": player_actor.id,
            "candidate": candidate.id,
            "offline": offline.id,
            "blocked": blocked.id,
        }

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client, session_factory, delivery, ids
    finally:
        app.dependency_overrides.pop(admin_promotion_notification_delivery, None)
        await engine.dispose()


async def test_superadmin_searches_users_reads_detail_and_filters_admin_candidates(
    admin_users_api: tuple[
        AsyncClient,
        async_sessionmaker,
        RecordingPromotionDelivery,
        dict[str, int],
    ],
) -> None:
    client, _, _, ids = admin_users_api

    users = await client.get("/api/v1/admin/users?query=player", headers=auth_headers(200))
    detail = await client.get(
        f"/api/v1/admin/users/{ids['offline']}",
        headers=auth_headers(200),
    )
    candidates = await client.get(
        "/api/v1/admin/users/admin-candidates?query=player",
        headers=auth_headers(200),
    )

    assert users.status_code == 200
    assert {item["id"] for item in users.json()["items"]} == {
        ids["player_actor"],
        ids["candidate"],
        ids["offline"],
        ids["blocked"],
    }
    assert all("telegram_id" not in item for item in users.json()["items"])
    assert detail.status_code == 200
    assert detail.json()["telegram_linked"] is False
    assert {item["id"] for item in candidates.json()["items"]} == {
        ids["player_actor"],
        ids["candidate"],
    }


async def test_user_management_requires_superadmin_and_maps_auth_and_missing_user(
    admin_users_api: tuple[
        AsyncClient,
        async_sessionmaker,
        RecordingPromotionDelivery,
        dict[str, int],
    ],
) -> None:
    client, _, _, _ = admin_users_api

    admin = await client.get("/api/v1/admin/users?query=player", headers=auth_headers(100))
    player = await client.get("/api/v1/admin/users?query=player", headers=auth_headers(300))
    missing = await client.get("/api/v1/admin/users/999", headers=auth_headers(200))
    unauthenticated = await client.get("/api/v1/admin/users?query=player")
    invalid_auth = await client.get(
        "/api/v1/admin/users?query=player",
        headers={"Authorization": "tma invalid"},
    )

    assert admin.status_code == 403
    assert player.status_code == 403
    assert missing.status_code == 404
    assert unauthenticated.status_code == 401
    assert invalid_auth.status_code == 401


async def test_promote_admin_commits_then_delivers_notification(
    admin_users_api: tuple[
        AsyncClient,
        async_sessionmaker,
        RecordingPromotionDelivery,
        dict[str, int],
    ],
) -> None:
    client, session_factory, delivery, ids = admin_users_api

    response = await client.post(
        f"/api/v1/admin/users/{ids['candidate']}/promote-admin",
        headers=auth_headers(200),
    )

    assert response.status_code == 200
    assert response.json()["role"] == "admin"
    assert len(delivery.users) == 1
    assert delivery.users[0].role == UserRole.ADMIN
    async with session_factory() as session:
        stored = await session.get(User, ids["candidate"])
    assert stored is not None
    assert stored.role == UserRole.ADMIN


async def test_promotion_failure_and_protected_targets_are_conflicts_without_mutation(
    admin_users_api: tuple[
        AsyncClient,
        async_sessionmaker,
        RecordingPromotionDelivery,
        dict[str, int],
    ],
) -> None:
    client, session_factory, delivery, ids = admin_users_api

    responses = [
        await client.post(
            f"/api/v1/admin/users/{target_id}/promote-admin",
            headers=auth_headers(200),
        )
        for target_id in (
            ids["root"],
            ids["other_superadmin"],
            ids["admin"],
            ids["offline"],
            ids["blocked"],
        )
    ]

    assert [response.status_code for response in responses] == [409, 409, 409, 409, 409]
    assert delivery.users == []
    async with session_factory() as session:
        root = await session.get(User, ids["root"])
        other_superadmin = await session.get(User, ids["other_superadmin"])
        admin = await session.get(User, ids["admin"])
        offline = await session.get(User, ids["offline"])
        blocked = await session.get(User, ids["blocked"])
    assert root is not None and root.role == UserRole.SUPERADMIN
    assert other_superadmin is not None and other_superadmin.role == UserRole.SUPERADMIN
    assert admin is not None and admin.role == UserRole.ADMIN
    assert offline is not None and offline.role == UserRole.PLAYER
    assert blocked is not None and blocked.role == UserRole.PLAYER


async def test_promotion_delivery_failure_does_not_roll_back_committed_role(
    admin_users_api: tuple[
        AsyncClient,
        async_sessionmaker,
        RecordingPromotionDelivery,
        dict[str, int],
    ],
) -> None:
    client, session_factory, delivery, ids = admin_users_api
    delivery.fail = True

    response = await client.post(
        f"/api/v1/admin/users/{ids['candidate']}/promote-admin",
        headers=auth_headers(200),
    )

    assert response.status_code == 200
    async with session_factory() as session:
        stored = await session.get(User, ids["candidate"])
    assert stored is not None
    assert stored.role == UserRole.ADMIN


async def test_rename_updates_canonical_name_and_rejects_stale_duplicate_or_invalid_input(
    admin_users_api: tuple[
        AsyncClient,
        async_sessionmaker,
        RecordingPromotionDelivery,
        dict[str, int],
    ],
) -> None:
    client, session_factory, _, ids = admin_users_api
    path = f"/api/v1/admin/users/{ids['candidate']}/name"

    renamed = await client.patch(
        path,
        headers=auth_headers(200),
        json={
            "display_name": "  Renamed   Player ",
            "expected_old_display_name": "Candidate Player",
        },
    )
    stale = await client.patch(
        path,
        headers=auth_headers(200),
        json={"display_name": "Another Name", "expected_old_display_name": "Candidate Player"},
    )
    duplicate = await client.patch(
        path,
        headers=auth_headers(200),
        json={"display_name": "Existing Admin", "expected_old_display_name": "Renamed Player"},
    )
    invalid = await client.patch(
        path,
        headers=auth_headers(200),
        json={"display_name": "   ", "expected_old_display_name": "Renamed Player"},
    )

    assert renamed.status_code == 200
    assert renamed.json()["display_name"] == "Renamed Player"
    assert stale.status_code == 409
    assert duplicate.status_code == 409
    assert invalid.status_code == 422
    async with session_factory() as session:
        stored = await session.get(User, ids["candidate"])
    assert stored is not None
    assert stored.display_name == "Renamed Player"


async def test_superadmin_can_update_gender_for_self_and_other_superadmin_metadata(
    admin_users_api: tuple[
        AsyncClient,
        async_sessionmaker,
        RecordingPromotionDelivery,
        dict[str, int],
    ],
) -> None:
    client, session_factory, _, ids = admin_users_api

    self_rename = await client.patch(
        f"/api/v1/admin/users/{ids['root']}/name",
        headers=auth_headers(200),
        json={
            "display_name": "Renamed Root",
            "expected_old_display_name": "Root Superadmin",
        },
    )
    gender = await client.patch(
        f"/api/v1/admin/users/{ids['other_superadmin']}/gender",
        headers=auth_headers(200),
        json={"gender": "female"},
    )

    assert self_rename.status_code == 200
    assert self_rename.json()["role"] == "superadmin"
    assert gender.status_code == 200
    assert gender.json()["gender"] == "female"
    async with session_factory() as session:
        root = await session.get(User, ids["root"])
        other = await session.get(User, ids["other_superadmin"])
    assert root is not None and root.role == UserRole.SUPERADMIN
    assert other is not None and other.role == UserRole.SUPERADMIN
    assert other.gender == UserGender.FEMALE


async def test_user_api_rejects_arbitrary_role_status_and_unsupported_mutations(
    admin_users_api: tuple[
        AsyncClient,
        async_sessionmaker,
        RecordingPromotionDelivery,
        dict[str, int],
    ],
) -> None:
    client, _, _, ids = admin_users_api
    user_path = f"/api/v1/admin/users/{ids['candidate']}"

    arbitrary = await client.patch(
        f"{user_path}/gender",
        headers=auth_headers(200),
        json={"gender": "male", "role": "superadmin", "status": "blocked"},
    )
    generic = await client.patch(
        user_path,
        headers=auth_headers(200),
        json={"role": "superadmin"},
    )
    deleted = await client.delete(user_path, headers=auth_headers(200))
    demoted = await client.post(f"{user_path}/demote-admin", headers=auth_headers(200))
    blocked = await client.post(f"{user_path}/block", headers=auth_headers(200))

    assert arbitrary.status_code == 422
    assert generic.status_code == 405
    assert deleted.status_code == 405
    assert demoted.status_code == 404
    assert blocked.status_code == 404
