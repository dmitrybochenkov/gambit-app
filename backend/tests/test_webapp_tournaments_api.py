import hashlib
import hmac
import json
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import pytest
from conftest import (
    build_player,
    seed_tournament_configs_async,
    seed_tournament_rules_async,
    seed_tournament_types_async,
    tournament_type_id,
)
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import dependencies
from app.api.v1 import tournaments as tournaments_api
from app.common.clock import FixedClock
from app.db.base import Base
from app.db.models import (
    ScoringConfig,
    Season,
    Tournament,
    TournamentRegistration,
    TournamentResult,
)
from app.db.models.enums import TournamentResultSource, TournamentStatus, UserStatus
from app.main import app
from app.services.tournament_service import TournamentService
from app.services.user_access_service import UserAccessService

TEST_BOT_TOKEN = "123456:test-token"


def signed_init_data(
    *,
    telegram_id: int,
    bot_token: str = TEST_BOT_TOKEN,
) -> str:
    data = {
        "auth_date": str(int(datetime.now(UTC).timestamp())),
        "query_id": "test-query",
        "user": json.dumps(
            {"id": telegram_id, "first_name": "Test"},
            separators=(",", ":"),
        ),
    }
    data_check_string = "\n".join(f"{key}={data[key]}" for key in sorted(data))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    data["hash"] = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(data)


@pytest.fixture
async def webapp_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[AsyncClient, async_sessionmaker]]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'webapp_tournaments.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    clock = FixedClock(datetime(2026, 9, 3, 12, tzinfo=ZoneInfo("Europe/Moscow")))
    monkeypatch.setattr(dependencies.settings, "telegram_bot_token", TEST_BOT_TOKEN)
    monkeypatch.setattr(dependencies.settings, "telegram_webapp_auth_max_age_seconds", 60)
    monkeypatch.setattr(dependencies, "user_access_service", UserAccessService(session_factory))
    monkeypatch.setattr(
        tournaments_api,
        "tournament_service",
        TournamentService(session_factory, clock=clock),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, session_factory
    await engine.dispose()


async def seed_player_week(session_factory: async_sessionmaker) -> dict[str, int]:
    async with session_factory() as session:
        config = ScoringConfig()
        session.add(config)
        await session.flush()
        await seed_tournament_types_async(session)
        await seed_tournament_configs_async(session)
        await seed_tournament_rules_async(session)
        season = Season(
            name="Test season",
            scoring_config_id=config.id,
            starts_at=date(2026, 9, 1),
            ends_at=None,
        )
        player = build_player(
            telegram_id=100,
            display_name="Player",
            status=UserStatus.ACTIVE,
        )
        other_player = build_player(
            telegram_id=200,
            display_name="Other",
            status=UserStatus.ACTIVE,
        )
        blocked_player = build_player(
            telegram_id=300,
            display_name="Blocked",
            status=UserStatus.BLOCKED,
        )
        session.add_all([season, player, other_player, blocked_player])
        await session.flush()
        current_open = Tournament(
            season_id=season.id,
            scoring_config_id=season.scoring_config_id,
            tournament_type_id=tournament_type_id("bounty_v2"),
            date=date(2026, 9, 3),
            status=TournamentStatus.ACTIVE,
            registration_open=True,
        )
        current_unapproved = Tournament(
            season_id=season.id,
            scoring_config_id=season.scoring_config_id,
            tournament_type_id=tournament_type_id("classic_v2"),
            date=date(2026, 9, 4),
            status=TournamentStatus.ACTIVE,
            registration_open=False,
        )
        closed_current = Tournament(
            season_id=season.id,
            scoring_config_id=season.scoring_config_id,
            tournament_type_id=tournament_type_id("freezeout_v2"),
            date=date(2026, 9, 5),
            status=TournamentStatus.CLOSED,
            registration_open=True,
            tournament_fund=1000,
        )
        next_week = Tournament(
            season_id=season.id,
            scoring_config_id=season.scoring_config_id,
            tournament_type_id=tournament_type_id("deep_stack"),
            date=date(2026, 9, 10),
            status=TournamentStatus.ACTIVE,
            registration_open=True,
        )
        session.add_all([current_open, current_unapproved, closed_current, next_week])
        await session.flush()
        await session.commit()
        return {
            "player_id": player.id,
            "other_player_id": other_player.id,
            "open_id": current_open.id,
            "unapproved_id": current_unapproved.id,
            "closed_id": closed_current.id,
            "next_week_id": next_week.id,
        }


def auth_headers(telegram_id: int = 100) -> dict[str, str]:
    return {"Authorization": f"tma {signed_init_data(telegram_id=telegram_id)}"}


async def test_week_endpoint_returns_player_current_week_tournaments(
    webapp_client: tuple[AsyncClient, async_sessionmaker],
) -> None:
    client, session_factory = webapp_client
    ids = await seed_player_week(session_factory)

    response = await client.get("/api/v1/tournaments/week", headers=auth_headers())

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body["items"]] == [ids["open_id"]]
    item = body["items"][0]
    assert item["date"] == "2026-09-03"
    assert item["type"] == {"code": "bounty_v2", "name": "Bounty"}
    assert "v2" not in item["type"]["name"].lower()
    assert item["description"]
    assert item["registration_open"] is True
    assert item["my_registration_status"] == "none"
    assert item["is_registered"] is False
    assert item["can_register"] is True
    assert item["can_cancel_registration"] is False
    assert "status" not in item
    assert "tournament_fund" not in item


async def test_tournament_details_include_public_config_without_admin_fields(
    webapp_client: tuple[AsyncClient, async_sessionmaker],
) -> None:
    client, session_factory = webapp_client
    ids = await seed_player_week(session_factory)

    response = await client.get(
        f"/api/v1/tournaments/{ids['open_id']}",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["type"] == {"code": "bounty_v2", "name": "Bounty"}
    assert body["economy"]["entry_fee"] == 600
    assert body["rules"]["knockout_mode"] == "small_big"
    assert "readiness" not in body
    assert "fund" not in body


async def test_registration_post_is_idempotent_and_me_registrations_are_owned(
    webapp_client: tuple[AsyncClient, async_sessionmaker],
) -> None:
    client, session_factory = webapp_client
    ids = await seed_player_week(session_factory)

    first = await client.post(
        f"/api/v1/tournaments/{ids['open_id']}/registration",
        headers=auth_headers(),
    )
    second = await client.post(
        f"/api/v1/tournaments/{ids['open_id']}/registration",
        headers=auth_headers(),
    )
    registrations = await client.get("/api/v1/me/registrations", headers=auth_headers())
    other_registrations = await client.get(
        "/api/v1/me/registrations",
        headers=auth_headers(telegram_id=200),
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["my_registration_status"] == "registered"
    assert second.json()["is_registered"] is True
    assert [item["id"] for item in registrations.json()["items"]] == [ids["open_id"]]
    assert other_registrations.json()["items"] == []
    async with session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(TournamentRegistration))
    assert count == 1


async def test_delete_registration_is_idempotent_and_does_not_touch_other_users(
    webapp_client: tuple[AsyncClient, async_sessionmaker],
) -> None:
    client, session_factory = webapp_client
    ids = await seed_player_week(session_factory)
    async with session_factory() as session:
        session.add(
            TournamentRegistration(
                tournament_id=ids["open_id"],
                player_id=ids["other_player_id"],
            )
        )
        await session.commit()

    first = await client.delete(
        f"/api/v1/tournaments/{ids['open_id']}/registration",
        headers=auth_headers(),
    )
    second = await client.delete(
        f"/api/v1/tournaments/{ids['open_id']}/registration",
        headers=auth_headers(),
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["is_registered"] is False
    async with session_factory() as session:
        rows = list((await session.scalars(select(TournamentRegistration))).all())
    assert [(row.tournament_id, row.player_id) for row in rows] == [
        (ids["open_id"], ids["other_player_id"])
    ]


async def test_registration_rejects_unavailable_tournaments_service_side(
    webapp_client: tuple[AsyncClient, async_sessionmaker],
) -> None:
    client, session_factory = webapp_client
    ids = await seed_player_week(session_factory)

    unapproved = await client.post(
        f"/api/v1/tournaments/{ids['unapproved_id']}/registration",
        headers=auth_headers(),
    )
    next_week = await client.post(
        f"/api/v1/tournaments/{ids['next_week_id']}/registration",
        headers=auth_headers(),
    )
    closed = await client.get(
        f"/api/v1/tournaments/{ids['closed_id']}",
        headers=auth_headers(),
    )

    assert unapproved.status_code == 409
    assert unapproved.json() == {
        "error": {
            "code": "conflict",
            "message": "Tournament is unavailable for registration",
        }
    }
    assert next_week.status_code == 409
    assert closed.status_code == 404


async def test_cancel_checked_in_registration_is_rejected(
    webapp_client: tuple[AsyncClient, async_sessionmaker],
) -> None:
    client, session_factory = webapp_client
    ids = await seed_player_week(session_factory)
    async with session_factory() as session:
        session.add(
            TournamentRegistration(
                tournament_id=ids["open_id"],
                player_id=ids["player_id"],
            )
        )
        session.add(
            TournamentResult(
                tournament_id=ids["open_id"],
                player_id=ids["player_id"],
                source=TournamentResultSource.REGISTERED,
            )
        )
        await session.commit()

    response = await client.delete(
        f"/api/v1/tournaments/{ids['open_id']}/registration",
        headers=auth_headers(),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


async def test_tournaments_api_uses_foundation_auth_error_contract(
    webapp_client: tuple[AsyncClient, async_sessionmaker],
) -> None:
    client, session_factory = webapp_client
    await seed_player_week(session_factory)

    missing = await client.get("/api/v1/tournaments/week")
    unknown = await client.get("/api/v1/tournaments/week", headers=auth_headers(telegram_id=404))
    blocked = await client.get("/api/v1/tournaments/week", headers=auth_headers(telegram_id=300))

    assert missing.status_code == 401
    assert missing.json() == {
        "error": {
            "code": "unauthorized",
            "message": "Invalid Telegram WebApp initData",
        }
    }
    assert unknown.status_code == 404
    assert unknown.json() == {
        "error": {
            "code": "not_found",
            "message": "User is not registered",
        }
    }
    assert blocked.status_code == 403
    assert blocked.json() == {
        "error": {
            "code": "forbidden",
            "message": "User is not active",
        }
    }
