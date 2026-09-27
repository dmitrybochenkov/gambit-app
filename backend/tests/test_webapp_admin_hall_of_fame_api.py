import hashlib
import hmac
import json
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import urlencode

import pytest
from conftest import seed_achievement_types_async
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import dependencies
from app.api.v1 import admin_hall_of_fame
from app.db.base import Base
from app.db.factories import create_user
from app.db.models import AchievementType, HallOfFameAchievement, ScoringConfig, Season, User
from app.db.models.enums import HallOfFameAchievementKind, UserRole
from app.main import app
from app.services.hall_of_fame_management_service import HallOfFameManagementService
from app.services.user_access_service import UserAccessService

TEST_BOT_TOKEN = "123456:test-token"


def signed_init_data(telegram_id: int) -> str:
    data = {
        "auth_date": str(int(datetime.now(UTC).timestamp())),
        "query_id": "admin-hall-api-test",
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


@pytest.fixture
async def admin_hall_api(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[AsyncClient, async_sessionmaker, dict[str, int]]]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'admin-hall.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    service = HallOfFameManagementService(session_factory)

    monkeypatch.setattr(dependencies.settings, "telegram_bot_token", TEST_BOT_TOKEN)
    monkeypatch.setattr(dependencies.settings, "telegram_webapp_auth_max_age_seconds", 60)
    monkeypatch.setattr(dependencies, "user_access_service", UserAccessService(session_factory))
    monkeypatch.setattr(admin_hall_of_fame, "hall_of_fame_management_service", service)

    async with session_factory() as session:
        await seed_achievement_types_async(session)
        config = ScoringConfig()
        session.add(config)
        await session.flush()
        season = Season(
            name="Осень 2026",
            starts_at=date(2026, 9, 1),
            ends_at=None,
            scoring_config_id=config.id,
        )
        superadmin = create_user(
            display_name="Root",
            telegram_id=100,
            role=UserRole.SUPERADMIN,
        )
        admin = create_user(display_name="Admin", telegram_id=101, role=UserRole.ADMIN)
        player_actor = create_user(display_name="Player Actor", telegram_id=102)
        first = create_user(display_name="First Winner", telegram_id=200)
        second = create_user(display_name="Second Winner")
        session.add_all([season, superadmin, admin, player_actor, first, second])
        await session.commit()
        ids = {
            "season": season.id,
            "superadmin": superadmin.id,
            "admin": admin.id,
            "player_actor": player_actor.id,
            "first": first.id,
            "second": second.id,
        }

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client, session_factory, ids
    finally:
        await engine.dispose()


async def test_superadmin_reads_seasons_metadata_players_and_all_occurrences(
    admin_hall_api: tuple[AsyncClient, async_sessionmaker, dict[str, int]],
) -> None:
    client, session_factory, ids = admin_hall_api
    async with session_factory() as session:
        session.add_all(
            [
                HallOfFameAchievement(
                    season_id=ids["season"],
                    player_id=ids["first"],
                    kind=HallOfFameAchievementKind.GRAND_MONTH,
                    awarded_at=date(2026, 9, 1),
                ),
                HallOfFameAchievement(
                    season_id=ids["season"],
                    player_id=ids["first"],
                    kind=HallOfFameAchievementKind.GRAND_MONTH,
                    awarded_at=date(2026, 9, 20),
                ),
            ]
        )
        await session.commit()

    seasons = await client.get(
        "/api/v1/admin/hall-of-fame/seasons",
        headers=auth_headers(100),
    )
    entry = await client.get(
        f"/api/v1/admin/hall-of-fame/seasons/{ids['season']}",
        headers=auth_headers(100),
    )
    metadata = await client.get(
        "/api/v1/admin/hall-of-fame/achievement-types",
        headers=auth_headers(100),
    )
    players = await client.get(
        "/api/v1/admin/hall-of-fame/players?query=Winner",
        headers=auth_headers(100),
    )

    assert seasons.status_code == 200
    assert seasons.json()["items"][0]["id"] == ids["season"]
    assert entry.status_code == 200
    grand_months = [item for item in entry.json()["achievements"] if item["kind"] == "grand_month"]
    assert len(grand_months) == 2
    assert len({item["id"] for item in grand_months}) == 2
    assert [item["awarded_at"] for item in grand_months] == ["2026-09-20", "2026-09-01"]
    assert [item["kind"] for item in metadata.json()["items"]] == [
        "rating_winner",
        "ko_rating_winner",
        "grand_season",
        "grand_month",
        "grand_knockout",
    ]
    grand_month_metadata = next(
        item for item in metadata.json()["items"] if item["kind"] == "grand_month"
    )
    assert grand_month_metadata["title"] == "Победитель Grand Month"
    assert {item["id"] for item in players.json()["items"]} == {
        ids["first"],
        ids["second"],
    }


async def test_hall_management_requires_signed_superadmin_auth(
    admin_hall_api: tuple[AsyncClient, async_sessionmaker, dict[str, int]],
) -> None:
    client, _, _ = admin_hall_api

    missing = await client.get("/api/v1/admin/hall-of-fame/seasons")
    invalid = await client.get(
        "/api/v1/admin/hall-of-fame/seasons",
        headers={"Authorization": "tma invalid"},
    )
    admin = await client.get(
        "/api/v1/admin/hall-of-fame/seasons",
        headers=auth_headers(101),
    )
    player = await client.get(
        "/api/v1/admin/hall-of-fame/seasons",
        headers=auth_headers(102),
    )

    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert admin.status_code == 403
    assert player.status_code == 403


async def test_singleton_post_replaces_existing_occurrence_in_place(
    admin_hall_api: tuple[AsyncClient, async_sessionmaker, dict[str, int]],
) -> None:
    client, session_factory, ids = admin_hall_api
    path = "/api/v1/admin/hall-of-fame/achievements"

    first = await client.post(
        path,
        headers=auth_headers(100),
        json={
            "season_id": ids["season"],
            "player_id": ids["first"],
            "kind": "rating_winner",
            "awarded_at": "2026-09-10",
        },
    )
    replacement = await client.post(
        path,
        headers=auth_headers(100),
        json={
            "season_id": ids["season"],
            "player_id": ids["second"],
            "kind": "rating_winner",
            "awarded_at": "2026-09-27",
        },
    )

    assert first.status_code == 200
    assert replacement.status_code == 200
    original = first.json()["achievements"][0]
    current = replacement.json()["achievements"][0]
    assert current["id"] == original["id"]
    assert current["player"]["id"] == ids["second"]
    assert current["awarded_at"] == "2026-09-27"
    async with session_factory() as session:
        rows = list(
            (
                await session.execute(
                    select(HallOfFameAchievement).where(
                        HallOfFameAchievement.kind == HallOfFameAchievementKind.RATING_WINNER
                    )
                )
            ).scalars()
        )
    assert len(rows) == 1


async def test_repeatable_awards_remain_distinct_and_revoke_targets_one_id(
    admin_hall_api: tuple[AsyncClient, async_sessionmaker, dict[str, int]],
) -> None:
    client, session_factory, ids = admin_hall_api
    payload = {
        "season_id": ids["season"],
        "player_id": ids["first"],
        "kind": "grand_knockout",
        "awarded_at": "2026-09-20",
    }

    first = await client.post(
        "/api/v1/admin/hall-of-fame/achievements",
        headers=auth_headers(100),
        json=payload,
    )
    second = await client.post(
        "/api/v1/admin/hall-of-fame/achievements",
        headers=auth_headers(100),
        json=payload,
    )
    achievements = second.json()["achievements"]
    duplicate_ids = [item["id"] for item in achievements if item["kind"] == "grand_knockout"]

    deleted = await client.delete(
        f"/api/v1/admin/hall-of-fame/achievements/{duplicate_ids[0]}",
        headers=auth_headers(100),
    )
    repeated_delete = await client.delete(
        f"/api/v1/admin/hall-of-fame/achievements/{duplicate_ids[0]}",
        headers=auth_headers(100),
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(duplicate_ids) == 2
    assert len(set(duplicate_ids)) == 2
    remaining = [
        item for item in deleted.json()["achievements"] if item["kind"] == "grand_knockout"
    ]
    assert [item["id"] for item in remaining] == [duplicate_ids[1]]
    assert repeated_delete.status_code == 404
    async with session_factory() as session:
        assert await session.get(User, ids["first"]) is not None
        rows = list((await session.execute(select(HallOfFameAchievement))).scalars())
    assert [row.id for row in rows] == [duplicate_ids[1]]


async def test_hall_award_rejects_missing_resources_and_client_metadata(
    admin_hall_api: tuple[AsyncClient, async_sessionmaker, dict[str, int]],
) -> None:
    client, session_factory, ids = admin_hall_api
    path = "/api/v1/admin/hall-of-fame/achievements"
    base = {
        "season_id": ids["season"],
        "player_id": ids["first"],
        "kind": "grand_month",
        "awarded_at": "2026-09-01",
    }

    missing_season = await client.post(
        path,
        headers=auth_headers(100),
        json={**base, "season_id": 999},
    )
    missing_player = await client.post(
        path,
        headers=auth_headers(100),
        json={**base, "player_id": 999},
    )
    invalid_kind = await client.post(
        path,
        headers=auth_headers(100),
        json={**base, "kind": "invented"},
    )
    forged_metadata = await client.post(
        path,
        headers=auth_headers(100),
        json={**base, "title": "Forged", "emoji": "X", "custom_emoji_id": "fake"},
    )

    assert missing_season.status_code == 404
    assert missing_player.status_code == 404
    assert invalid_kind.status_code == 422
    assert forged_metadata.status_code == 422
    async with session_factory() as session:
        assert list((await session.execute(select(HallOfFameAchievement))).scalars()) == []


async def test_valid_enum_without_canonical_metadata_is_not_found_and_not_persisted(
    admin_hall_api: tuple[AsyncClient, async_sessionmaker, dict[str, int]],
) -> None:
    client, session_factory, ids = admin_hall_api
    async with session_factory() as session:
        await session.execute(delete(AchievementType).where(AchievementType.kind == "grand_month"))
        await session.commit()

    response = await client.post(
        "/api/v1/admin/hall-of-fame/achievements",
        headers=auth_headers(100),
        json={
            "season_id": ids["season"],
            "player_id": ids["first"],
            "kind": "grand_month",
            "awarded_at": "2026-09-01",
        },
    )

    assert response.status_code == 404
    async with session_factory() as session:
        assert list((await session.execute(select(HallOfFameAchievement))).scalars()) == []
