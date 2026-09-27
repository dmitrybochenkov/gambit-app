import hashlib
import hmac
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import dependencies, registration_review_dependencies
from app.api.registration_review_dependencies import registration_review_notification_delivery
from app.api.v1 import admin_registrations
from app.bot.telegram import runtime
from app.db.base import Base
from app.db.factories import create_user
from app.db.models import RegistrationRequest, User
from app.db.models.enums import (
    RegistrationRequestStatus,
    RegistrationRequestType,
    UserRole,
    UserStatus,
)
from app.main import app
from app.services.dto.registrations import RegistrationReviewOutcomeView
from app.services.registration_review_service import RegistrationReviewService
from app.services.registration_review_use_cases import RegistrationReviewUseCases
from app.services.user_access_service import UserAccessService

TEST_BOT_TOKEN = "123456:test-token"


def signed_init_data(telegram_id: int) -> str:
    data = {
        "auth_date": str(int(datetime.now(UTC).timestamp())),
        "query_id": "admin-registration-api-test",
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


class RecordingDelivery:
    def __init__(self) -> None:
        self.outcomes: list[RegistrationReviewOutcomeView] = []
        self.fail = False

    async def deliver(self, outcome: RegistrationReviewOutcomeView) -> None:
        self.outcomes.append(outcome)
        if self.fail:
            raise RuntimeError("delivery unavailable")


def test_registration_review_delivery_dependency_reads_runtime_bot_at_call_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_bot = object()
    monkeypatch.setattr(runtime, "telegram_bot", current_bot)

    delivery = registration_review_dependencies.registration_review_notification_delivery()

    assert getattr(delivery, "_bot") is current_bot


@pytest.fixture
async def registration_review_api(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[AsyncClient, async_sessionmaker, RecordingDelivery, dict[str, int]]]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'registration-review.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    service = RegistrationReviewService(session_factory)
    delivery = RecordingDelivery()

    monkeypatch.setattr(dependencies.settings, "telegram_bot_token", TEST_BOT_TOKEN)
    monkeypatch.setattr(dependencies.settings, "telegram_webapp_auth_max_age_seconds", 60)
    monkeypatch.setattr(dependencies, "user_access_service", UserAccessService(session_factory))
    monkeypatch.setattr(admin_registrations, "registration_review_service", service)
    monkeypatch.setattr(
        admin_registrations,
        "registration_review_use_cases",
        RegistrationReviewUseCases(service),
    )
    app.dependency_overrides[registration_review_notification_delivery] = lambda: delivery

    async with session_factory() as session:
        superadmin = create_user(
            display_name="Canonical Superadmin",
            telegram_id=200,
            role=UserRole.SUPERADMIN,
        )
        admin = create_user(display_name="Admin", telegram_id=100, role=UserRole.ADMIN)
        player = create_user(display_name="Player", telegram_id=300)
        historical = create_user(display_name="Historical Player")
        session.add_all([superadmin, admin, player, historical])
        await session.flush()
        requests = [
            RegistrationRequest(
                telegram_id=1001,
                request_type=RegistrationRequestType.NEW_PLAYER,
                status=RegistrationRequestStatus.PENDING,
                requested_display_name="New Player",
                requested_display_name_normalized="new player",
            ),
            RegistrationRequest(
                telegram_id=1002,
                request_type=RegistrationRequestType.LINK_EXISTING_PLAYER,
                status=RegistrationRequestStatus.PENDING,
                requested_link_name="Historical Player",
            ),
            *[
                RegistrationRequest(
                    telegram_id=telegram_id,
                    request_type=RegistrationRequestType.NEW_PLAYER,
                    status=RegistrationRequestStatus.PENDING,
                    requested_display_name=f"Player {telegram_id}",
                    requested_display_name_normalized=f"player {telegram_id}",
                )
                for telegram_id in range(1003, 1007)
            ],
        ]
        session.add_all(requests)
        await session.commit()
        ids = {
            "new_request_id": requests[0].id,
            "link_request_id": requests[1].id,
            "historical_id": historical.id,
        }

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client, session_factory, delivery, ids
    finally:
        app.dependency_overrides.pop(registration_review_notification_delivery, None)
        await engine.dispose()


async def test_superadmin_lists_paginated_pending_reviews_and_reads_detail(
    registration_review_api: tuple[
        AsyncClient,
        async_sessionmaker,
        RecordingDelivery,
        dict[str, int],
    ],
) -> None:
    client, _, _, ids = registration_review_api

    first = await client.get(
        "/api/v1/admin/registrations/pending?page=0&page_size=5",
        headers=auth_headers(200),
    )
    second = await client.get(
        "/api/v1/admin/registrations/pending?page=1&page_size=5",
        headers=auth_headers(200),
    )
    detail = await client.get(
        f"/api/v1/admin/registrations/{ids['link_request_id']}",
        headers=auth_headers(200),
    )

    assert first.status_code == 200
    assert (first.json()["page"], first.json()["total_pages"], first.json()["total_items"]) == (
        0,
        2,
        6,
    )
    assert len(first.json()["items"]) == 5
    assert second.status_code == 200
    first_ids = {item["request"]["id"] for item in first.json()["items"]}
    second_ids = {item["request"]["id"] for item in second.json()["items"]}
    assert len(second_ids) == 1
    assert first_ids.isdisjoint(second_ids)
    assert detail.status_code == 200
    assert detail.json()["request"]["request_type"] == "link_existing_player"
    assert [item["user"]["id"] for item in detail.json()["candidates"]] == [ids["historical_id"]]


async def test_registration_review_reads_require_superadmin_and_map_missing_or_auth_errors(
    registration_review_api: tuple[
        AsyncClient,
        async_sessionmaker,
        RecordingDelivery,
        dict[str, int],
    ],
) -> None:
    client, _, _, _ = registration_review_api

    admin = await client.get("/api/v1/admin/registrations/pending", headers=auth_headers(100))
    player = await client.get("/api/v1/admin/registrations/pending", headers=auth_headers(300))
    missing = await client.get("/api/v1/admin/registrations/999", headers=auth_headers(200))
    unauthenticated = await client.get("/api/v1/admin/registrations/pending")
    invalid_auth = await client.get(
        "/api/v1/admin/registrations/pending",
        headers={"Authorization": "tma invalid"},
    )

    assert admin.status_code == 403
    assert player.status_code == 403
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"
    assert unauthenticated.status_code == 401
    assert invalid_auth.status_code == 401


async def test_http_approve_new_player_commits_then_invokes_shared_delivery(
    registration_review_api: tuple[
        AsyncClient,
        async_sessionmaker,
        RecordingDelivery,
        dict[str, int],
    ],
) -> None:
    client, session_factory, delivery, ids = registration_review_api

    response = await client.post(
        f"/api/v1/admin/registrations/{ids['new_request_id']}/approve",
        headers=auth_headers(200),
        json={},
    )

    assert response.status_code == 200
    assert response.json()["decision"] == "approved"
    assert response.json()["reviewer"]["display_name"] == "Canonical Superadmin"
    assert "notification_recipients" not in response.json()
    assert len(delivery.outcomes) == 1
    assert delivery.outcomes[0].request.status == "approved"
    async with session_factory() as session:
        request = await session.get(RegistrationRequest, ids["new_request_id"])
        user = await session.scalar(select(User).where(User.telegram_id == 1001))
    assert request is not None
    assert request.status == RegistrationRequestStatus.APPROVED
    assert request.reviewed_at is not None
    assert user is not None
    assert user.status == UserStatus.ACTIVE
    assert user.role == UserRole.PLAYER


async def test_http_reject_commits_without_creating_user_and_invokes_shared_delivery(
    registration_review_api: tuple[
        AsyncClient,
        async_sessionmaker,
        RecordingDelivery,
        dict[str, int],
    ],
) -> None:
    client, session_factory, delivery, ids = registration_review_api

    response = await client.post(
        f"/api/v1/admin/registrations/{ids['new_request_id']}/reject",
        headers=auth_headers(200),
    )

    assert response.status_code == 200
    assert response.json()["decision"] == "rejected"
    assert len(delivery.outcomes) == 1
    async with session_factory() as session:
        request = await session.get(RegistrationRequest, ids["new_request_id"])
        user = await session.scalar(select(User).where(User.telegram_id == 1001))
    assert request is not None
    assert request.status == RegistrationRequestStatus.REJECTED
    assert request.reviewed_at is not None
    assert user is None


async def test_link_candidate_is_validated_without_persistence_and_revalidated_on_approve(
    registration_review_api: tuple[
        AsyncClient,
        async_sessionmaker,
        RecordingDelivery,
        dict[str, int],
    ],
) -> None:
    client, session_factory, delivery, ids = registration_review_api
    path = f"/api/v1/admin/registrations/{ids['link_request_id']}"

    selected = await client.post(
        f"{path}/candidate",
        headers=auth_headers(200),
        json={"candidate_user_id": ids["historical_id"]},
    )
    async with session_factory() as session:
        request_before_approval = await session.get(RegistrationRequest, ids["link_request_id"])
    approved = await client.post(
        f"{path}/approve",
        headers=auth_headers(200),
        json={"candidate_user_id": ids["historical_id"]},
    )

    assert selected.status_code == 200
    assert selected.json()["selected_candidate"]["user"]["id"] == ids["historical_id"]
    assert request_before_approval is not None
    assert request_before_approval.candidate_user_id is None
    assert approved.status_code == 200
    assert approved.json()["user"]["id"] == ids["historical_id"]
    assert len(delivery.outcomes) == 1
    async with session_factory() as session:
        historical = await session.get(User, ids["historical_id"])
    assert historical is not None
    assert historical.telegram_id == 1002


async def test_invalid_or_stale_candidate_does_not_review_request(
    registration_review_api: tuple[
        AsyncClient,
        async_sessionmaker,
        RecordingDelivery,
        dict[str, int],
    ],
) -> None:
    client, session_factory, delivery, ids = registration_review_api
    path = f"/api/v1/admin/registrations/{ids['link_request_id']}"

    invalid = await client.post(
        f"{path}/candidate",
        headers=auth_headers(200),
        json={"candidate_user_id": 999},
    )
    selected = await client.post(
        f"{path}/candidate",
        headers=auth_headers(200),
        json={"candidate_user_id": ids["historical_id"]},
    )
    async with session_factory() as session:
        historical = await session.get(User, ids["historical_id"])
        assert historical is not None
        historical.telegram_id = 9000
        await session.commit()
    stale = await client.post(
        f"{path}/approve",
        headers=auth_headers(200),
        json={"candidate_user_id": ids["historical_id"]},
    )

    assert invalid.status_code == 404
    assert selected.status_code == 200
    assert stale.status_code == 404
    assert delivery.outcomes == []
    async with session_factory() as session:
        request = await session.get(RegistrationRequest, ids["link_request_id"])
    assert request is not None
    assert request.status == RegistrationRequestStatus.PENDING
    assert request.reviewed_at is None


async def test_approve_payload_rejects_client_controlled_reviewer_state(
    registration_review_api: tuple[
        AsyncClient,
        async_sessionmaker,
        RecordingDelivery,
        dict[str, int],
    ],
) -> None:
    client, _, delivery, ids = registration_review_api

    response = await client.post(
        f"/api/v1/admin/registrations/{ids['new_request_id']}/approve",
        headers=auth_headers(200),
        json={"reviewer_telegram_id": 999, "status": "approved"},
    )

    assert response.status_code == 422
    assert delivery.outcomes == []


async def test_repeated_decision_and_review_detail_are_conflicts_without_delivery(
    registration_review_api: tuple[
        AsyncClient,
        async_sessionmaker,
        RecordingDelivery,
        dict[str, int],
    ],
) -> None:
    client, _, delivery, ids = registration_review_api
    path = f"/api/v1/admin/registrations/{ids['new_request_id']}"

    first = await client.post(f"{path}/reject", headers=auth_headers(200))
    repeated = await client.post(f"{path}/approve", headers=auth_headers(200), json={})
    detail = await client.get(path, headers=auth_headers(200))

    assert first.status_code == 200
    assert repeated.status_code == 409
    assert detail.status_code == 409
    assert len(delivery.outcomes) == 1


async def test_delivery_failure_after_commit_remains_http_success(
    registration_review_api: tuple[
        AsyncClient,
        async_sessionmaker,
        RecordingDelivery,
        dict[str, int],
    ],
) -> None:
    client, session_factory, delivery, ids = registration_review_api
    delivery.fail = True

    response = await client.post(
        f"/api/v1/admin/registrations/{ids['new_request_id']}/approve",
        headers=auth_headers(200),
        json={},
    )

    assert response.status_code == 200
    assert len(delivery.outcomes) == 1
    async with session_factory() as session:
        request = await session.get(RegistrationRequest, ids["new_request_id"])
    assert request is not None
    assert request.status == RegistrationRequestStatus.APPROVED


async def test_identity_conflict_is_409_and_attempts_no_delivery(
    registration_review_api: tuple[
        AsyncClient,
        async_sessionmaker,
        RecordingDelivery,
        dict[str, int],
    ],
) -> None:
    client, session_factory, delivery, ids = registration_review_api
    async with session_factory() as session:
        session.add(create_user(display_name="New Player", telegram_id=9000))
        await session.commit()

    response = await client.post(
        f"/api/v1/admin/registrations/{ids['new_request_id']}/approve",
        headers=auth_headers(200),
        json={},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"
    assert delivery.outcomes == []
    async with session_factory() as session:
        request = await session.get(RegistrationRequest, ids["new_request_id"])
    assert request is not None
    assert request.status == RegistrationRequestStatus.PENDING
