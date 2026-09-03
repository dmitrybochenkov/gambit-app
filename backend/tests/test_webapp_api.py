import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import urlencode

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import dependencies
from app.api.auth import (
    TelegramWebAppAuthError,
    TelegramWebAppInitDataVerifier,
    authorization_to_init_data,
)
from app.common.clock import FixedClock
from app.db.models.enums import UserGender, UserRole, UserStatus
from app.main import app
from app.services.dto.users import UserView

TEST_BOT_TOKEN = "123456:test-token"
NOW = datetime(2026, 9, 3, 12, tzinfo=UTC)


def signed_init_data(
    *,
    telegram_id: int = 123,
    auth_date: datetime = NOW,
    bot_token: str = TEST_BOT_TOKEN,
    user: str | None = None,
    extra: dict[str, str] | None = None,
) -> str:
    data = {
        "auth_date": str(int(auth_date.timestamp())),
        "query_id": "test-query",
        "user": user
        if user is not None
        else json.dumps(
            {"id": telegram_id, "first_name": "Test"},
            separators=(",", ":"),
        ),
    }
    if extra:
        data.update(extra)
    data_check_string = "\n".join(f"{key}={data[key]}" for key in sorted(data))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    data["hash"] = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(data)


def signed_raw_init_data(data: dict[str, str], bot_token: str = TEST_BOT_TOKEN) -> str:
    data_check_string = "\n".join(f"{key}={data[key]}" for key in sorted(data))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    return urlencode(
        {
            **data,
            "hash": hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest(),
        }
    )


def verifier(max_age_seconds: int = 60) -> TelegramWebAppInitDataVerifier:
    return TelegramWebAppInitDataVerifier(
        bot_token=TEST_BOT_TOKEN,
        max_age_seconds=max_age_seconds,
        clock=FixedClock(NOW),
    )


def fresh_init_data() -> str:
    return signed_init_data(auth_date=datetime.now(UTC))


def user_view(
    *,
    user_id: int = 1,
    telegram_id: int | None = 123,
    role: UserRole = UserRole.PLAYER,
    status: UserStatus = UserStatus.ACTIVE,
    gender: UserGender | None = None,
) -> UserView:
    return UserView(
        id=user_id,
        telegram_id=telegram_id,
        display_name="Дима",
        status=status,
        role=role,
        gender=gender,
    )


def test_authorization_header_uses_single_tma_scheme() -> None:
    raw = "auth_date=1&hash=test&user=%7B%7D"

    assert authorization_to_init_data(f"tma {raw}") == raw

    with pytest.raises(TelegramWebAppAuthError):
        authorization_to_init_data(None)
    with pytest.raises(TelegramWebAppAuthError):
        authorization_to_init_data(f"Bearer {raw}")


def test_webapp_init_data_verifier_accepts_valid_signed_data() -> None:
    identity = verifier().verify(signed_init_data())

    assert identity.telegram_id == 123


@pytest.mark.parametrize(
    "raw_init_data",
    [
        signed_init_data().replace("hash=", "hash=bad"),
        "auth_date=1&user=%7B%7D",
        signed_raw_init_data({"auth_date": str(int(NOW.timestamp()))}),
        signed_init_data(auth_date=NOW - timedelta(seconds=61)),
        signed_init_data(auth_date=NOW + timedelta(seconds=61)),
        signed_init_data(auth_date=NOW, user="{"),
        signed_init_data(auth_date=NOW, user=json.dumps({"first_name": "No id"})),
        signed_init_data() + "&auth_date=1",
    ],
)
def test_webapp_init_data_verifier_rejects_invalid_data(raw_init_data: str) -> None:
    with pytest.raises(TelegramWebAppAuthError):
        verifier().verify(raw_init_data)


def test_webapp_init_data_verifier_rejects_malformed_auth_date() -> None:
    raw = signed_init_data(extra={"auth_date": "not-a-timestamp"})

    with pytest.raises(TelegramWebAppAuthError):
        verifier().verify(raw)


async def get_me(raw_init_data: str | None = None) -> tuple[int, dict]:
    transport = ASGITransport(app=app)
    headers = {"Authorization": f"tma {raw_init_data}"} if raw_init_data is not None else {}
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/me", headers=headers)
    return response.status_code, response.json()


async def test_me_rejects_missing_and_malformed_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dependencies.settings, "telegram_bot_token", TEST_BOT_TOKEN)

    missing_status, missing_body = await get_me()
    malformed_status, malformed_body = await get_me("not-valid")

    assert missing_status == 401
    assert missing_body == {
        "error": {
            "code": "unauthorized",
            "message": "Invalid Telegram WebApp initData",
        }
    }
    assert malformed_status == 401
    assert malformed_body == {
        "error": {
            "code": "unauthorized",
            "message": "Invalid Telegram WebApp initData",
        }
    }


async def test_me_returns_not_found_for_valid_unlinked_telegram_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = SimpleNamespace(get_by_telegram_id=AsyncMock(return_value=None))
    monkeypatch.setattr(dependencies, "user_access_service", service)
    monkeypatch.setattr(dependencies.settings, "telegram_bot_token", TEST_BOT_TOKEN)
    monkeypatch.setattr(dependencies.settings, "telegram_webapp_auth_max_age_seconds", 60)

    status_code, body = await get_me(fresh_init_data())

    assert status_code == 404
    assert body == {
        "error": {
            "code": "not_found",
            "message": "User is not registered",
        }
    }
    service.get_by_telegram_id.assert_awaited_once_with(123)


async def test_me_returns_forbidden_for_blocked_user(monkeypatch: pytest.MonkeyPatch) -> None:
    service = SimpleNamespace(
        get_by_telegram_id=AsyncMock(
            return_value=user_view(status=UserStatus.BLOCKED),
        )
    )
    monkeypatch.setattr(dependencies, "user_access_service", service)
    monkeypatch.setattr(dependencies.settings, "telegram_bot_token", TEST_BOT_TOKEN)
    monkeypatch.setattr(dependencies.settings, "telegram_webapp_auth_max_age_seconds", 60)

    status_code, body = await get_me(fresh_init_data())

    assert status_code == 403
    assert body == {
        "error": {
            "code": "forbidden",
            "message": "User is not active",
        }
    }


@pytest.mark.parametrize(
    ("role", "expected_role"),
    [
        (UserRole.PLAYER, "player"),
        (UserRole.ADMIN, "admin"),
        (UserRole.SUPERADMIN, "superadmin"),
    ],
)
async def test_me_returns_active_user_payload_for_all_roles(
    role: UserRole,
    expected_role: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = SimpleNamespace(
        get_by_telegram_id=AsyncMock(
            return_value=user_view(
                user_id=42,
                role=role,
                gender=UserGender.MALE if role == UserRole.ADMIN else None,
            ),
        )
    )
    monkeypatch.setattr(dependencies, "user_access_service", service)
    monkeypatch.setattr(dependencies.settings, "telegram_bot_token", TEST_BOT_TOKEN)
    monkeypatch.setattr(dependencies.settings, "telegram_webapp_auth_max_age_seconds", 60)

    status_code, body = await get_me(fresh_init_data())

    assert status_code == 200
    assert body == {
        "id": 42,
        "display_name": "Дима",
        "role": expected_role,
        "gender": "male" if role == UserRole.ADMIN else None,
        "status": "active",
    }
    assert "display_name_normalized" not in body
    assert "telegram_id" not in body


async def test_me_appears_in_openapi() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/openapi.json")

    assert response.status_code == 200
    assert "/api/v1/me" in response.json()["paths"]
