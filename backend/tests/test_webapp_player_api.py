import hashlib
import hmac
import json
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import pytest
from conftest import (
    build_player,
    seed_tournament_types_async,
    tournament_type_id,
)
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import dependencies
from app.api.v1 import hall_of_fame, history, profile, ratings, rewards
from app.common.clock import FixedClock
from app.db.base import Base
from app.db.models import (
    PlayerReward,
    ScoringConfig,
    Season,
    SeasonHallOfFame,
    Tournament,
    TournamentResult,
)
from app.db.models.enums import TournamentResultSource, TournamentStatus, UserGender, UserStatus
from app.main import app
from app.services.player_reward_service import PlayerRewardService
from app.services.profile_service import ProfileService
from app.services.rating_service import RatingService
from app.services.user_access_service import UserAccessService
from app.services.user_statistics_service import UserStatisticsService

TEST_BOT_TOKEN = "123456:test-token"
NOW = datetime(2026, 9, 3, 12, tzinfo=ZoneInfo("Europe/Moscow"))


def signed_init_data(telegram_id: int) -> str:
    data = {
        "auth_date": str(int(datetime.now(UTC).timestamp())),
        "query_id": "test-query",
        "user": json.dumps(
            {"id": telegram_id, "first_name": "Test"},
            separators=(",", ":"),
        ),
    }
    data_check_string = "\n".join(f"{key}={data[key]}" for key in sorted(data))
    secret_key = hmac.new(b"WebAppData", TEST_BOT_TOKEN.encode(), hashlib.sha256).digest()
    data["hash"] = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(data)


def auth_headers(telegram_id: int = 100) -> dict[str, str]:
    return {"Authorization": f"tma {signed_init_data(telegram_id)}"}


@pytest.fixture
async def player_api_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[AsyncClient, async_sessionmaker]]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'webapp_player.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    clock = FixedClock(NOW)
    monkeypatch.setattr(dependencies.settings, "telegram_bot_token", TEST_BOT_TOKEN)
    monkeypatch.setattr(dependencies.settings, "telegram_webapp_auth_max_age_seconds", 60)
    monkeypatch.setattr(dependencies, "user_access_service", UserAccessService(session_factory))
    monkeypatch.setattr(ratings, "rating_service", RatingService(session_factory, clock=clock))
    monkeypatch.setattr(profile, "profile_service", ProfileService(session_factory, clock=clock))
    monkeypatch.setattr(
        history,
        "user_statistics_service",
        UserStatisticsService(session_factory, clock=clock),
    )
    monkeypatch.setattr(
        hall_of_fame,
        "user_statistics_service",
        UserStatisticsService(session_factory, clock=clock),
    )
    monkeypatch.setattr(
        rewards,
        "player_reward_service",
        PlayerRewardService(session_factory, clock=clock),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, session_factory
    await engine.dispose()


async def seed_player_api_data(session_factory: async_sessionmaker) -> dict[str, int]:
    async with session_factory() as session:
        config = ScoringConfig()
        session.add(config)
        await session.flush()
        await seed_tournament_types_async(session)
        previous_season = Season(
            name="Весна 2026",
            scoring_config_id=config.id,
            starts_at=date(2026, 4, 1),
            ends_at=date(2026, 6, 30),
        )
        current_season = Season(
            name="Лето 2026",
            scoring_config_id=config.id,
            starts_at=date(2026, 7, 1),
            ends_at=date(2026, 9, 30),
        )
        player = build_player(
            telegram_id=100,
            display_name="Player",
            gender=UserGender.FEMALE,
            status=UserStatus.ACTIVE,
        )
        rival = build_player(telegram_id=200, display_name="Rival", status=UserStatus.ACTIVE)
        blocked = build_player(telegram_id=300, display_name="Blocked", status=UserStatus.BLOCKED)
        session.add_all([previous_season, current_season, player, rival, blocked])
        await session.flush()
        previous = Tournament(
            season_id=previous_season.id,
            tournament_type_id=tournament_type_id("classic_v2"),
            date=date(2026, 6, 15),
            status=TournamentStatus.CLOSED,
            tournament_fund=1000,
        )
        current = Tournament(
            season_id=current_season.id,
            tournament_type_id=tournament_type_id("bounty_v2"),
            date=date(2026, 8, 20),
            status=TournamentStatus.CLOSED,
            tournament_fund=1000,
        )
        other = Tournament(
            season_id=current_season.id,
            tournament_type_id=tournament_type_id("freezeout_v2"),
            date=date(2026, 8, 21),
            status=TournamentStatus.CLOSED,
            tournament_fund=1000,
        )
        session.add_all([previous, current, other])
        await session.flush()
        session.add_all(
            [
                TournamentResult(
                    tournament_id=previous.id,
                    player_id=player.id,
                    source=TournamentResultSource.REGISTERED,
                    place=1,
                    tournament_points=Decimal("90"),
                    knockout_points=Decimal("0"),
                    bonus_points=0,
                ),
                TournamentResult(
                    tournament_id=current.id,
                    player_id=player.id,
                    source=TournamentResultSource.REGISTERED,
                    place=2,
                    knockouts_count=3,
                    big_knockouts_count=1,
                    tournament_points=Decimal("100"),
                    knockout_points=Decimal("35"),
                    bonus_points=5,
                ),
                TournamentResult(
                    tournament_id=current.id,
                    player_id=rival.id,
                    source=TournamentResultSource.REGISTERED,
                    place=1,
                    knockouts_count=1,
                    big_knockouts_count=0,
                    tournament_points=Decimal("120"),
                    knockout_points=Decimal("10"),
                    bonus_points=0,
                ),
                TournamentResult(
                    tournament_id=other.id,
                    player_id=rival.id,
                    source=TournamentResultSource.REGISTERED,
                    place=1,
                    knockouts_count=9,
                    big_knockouts_count=0,
                    tournament_points=Decimal("20"),
                    knockout_points=Decimal("90"),
                    bonus_points=0,
                ),
            ]
        )
        session.add(
            SeasonHallOfFame(
                season_id=previous_season.id,
                champion_player_id=player.id,
                knockout_player_id=rival.id,
                champion_photo_file_id="telegram-champion-file-id",
                knockout_photo_file_id="telegram-ko-file-id",
                updated_by_user_id=player.id,
            )
        )
        reward = PlayerReward(
            player_id=player.id,
            chips_amount=40_000,
            source_tournament_id=current.id,
            source_place=1,
            issued_at=datetime(2026, 8, 20, 0, 0, tzinfo=ZoneInfo("Europe/Moscow")),
            valid_through=date(2026, 9, 10),
        )
        other_reward = PlayerReward(
            player_id=rival.id,
            chips_amount=30_000,
            source_tournament_id=current.id,
            source_place=2,
            issued_at=datetime(2026, 8, 20, 0, 0, tzinfo=ZoneInfo("Europe/Moscow")),
            valid_through=date(2026, 9, 10),
        )
        session.add_all([reward, other_reward])
        await session.commit()
        return {
            "previous_season_id": previous_season.id,
            "current_season_id": current_season.id,
            "player_id": player.id,
            "rival_id": rival.id,
            "current_tournament_id": current.id,
            "other_tournament_id": other.id,
        }


async def test_ratings_return_semantic_achievement_counts(
    player_api_client: tuple[AsyncClient, async_sessionmaker],
) -> None:
    client, session_factory = player_api_client
    await seed_player_api_data(session_factory)

    ordinary = await client.get("/api/v1/ratings", headers=auth_headers())
    knockouts = await client.get("/api/v1/ratings/knockouts", headers=auth_headers())

    assert ordinary.status_code == 200
    assert [item["player"]["display_name"] for item in ordinary.json()["items"]] == [
        "Rival",
        "Player",
    ]
    assert ordinary.json()["items"][1]["points"] == "140.00"
    assert ordinary.json()["items"][1]["champion_titles_count"] == 1
    assert "knockout_titles_count" not in ordinary.json()["items"][0]
    assert "💍" not in json.dumps(ordinary.json(), ensure_ascii=False)

    assert knockouts.status_code == 200
    assert [item["player"]["display_name"] for item in knockouts.json()["items"]] == [
        "Rival",
        "Player",
    ]
    assert knockouts.json()["items"][0]["total_knockouts_count"] == 10
    assert knockouts.json()["items"][0]["knockout_titles_count"] == 1
    assert "champion_titles_count" not in knockouts.json()["items"][0]
    assert "💥" not in json.dumps(knockouts.json(), ensure_ascii=False)


async def test_rating_supports_explicit_started_season_and_rejects_unknown(
    player_api_client: tuple[AsyncClient, async_sessionmaker],
) -> None:
    client, session_factory = player_api_client
    ids = await seed_player_api_data(session_factory)

    selected = await client.get(
        f"/api/v1/ratings?season_id={ids['previous_season_id']}",
        headers=auth_headers(),
    )
    missing = await client.get("/api/v1/ratings?season_id=999", headers=auth_headers())

    assert selected.status_code == 200
    assert selected.json()["title"] == "Рейтинг — Весна 2026"
    assert [item["player"]["display_name"] for item in selected.json()["items"]] == ["Player"]
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"


async def test_profile_returns_current_actor_semantic_stats(
    player_api_client: tuple[AsyncClient, async_sessionmaker],
) -> None:
    client, session_factory = player_api_client
    await seed_player_api_data(session_factory)

    response = await client.get("/api/v1/me/profile", headers=auth_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["display_name"] == "Player"
    assert body["gender"] == "female"
    assert body["points"] == "140.00"
    assert body["tournaments_count"] == 1
    assert body["knockouts_count"] == 3
    assert body["big_knockouts_count"] == 1
    assert body["places"]["second"] == 1
    assert body["champion_titles_count"] == 1
    assert body["knockout_titles_count"] == 0
    assert "display_name_normalized" not in body
    assert "telegram_id" not in body
    assert "💍" not in json.dumps(body, ensure_ascii=False)


async def test_history_is_private_and_uses_public_tournament_names(
    player_api_client: tuple[AsyncClient, async_sessionmaker],
) -> None:
    client, session_factory = player_api_client
    ids = await seed_player_api_data(session_factory)

    history = await client.get("/api/v1/me/history", headers=auth_headers())
    own_detail = await client.get(
        f"/api/v1/me/history/{ids['current_tournament_id']}",
        headers=auth_headers(),
    )
    other_detail = await client.get(
        f"/api/v1/me/history/{ids['other_tournament_id']}",
        headers=auth_headers(),
    )

    assert history.status_code == 200
    assert [item["tournament_id"] for item in history.json()["items"]] == [
        ids["current_tournament_id"],
        ids["current_tournament_id"] - 1,
    ]
    current = history.json()["items"][0]
    assert current["type"] == {"code": "bounty_v2", "name": "Bounty"}
    assert current["place"] == 2
    assert current["tournament_points"] == "100.00"
    assert current["knockout_points"] == "35.00"
    assert current["bonus_points"] == 5
    assert current["total_points"] == "140.00"
    assert current["knockouts_count"] == 3
    assert current["big_knockouts_count"] == 1

    assert own_detail.status_code == 200
    assert own_detail.json()["my_result"]["player_id"] == ids["player_id"]
    assert other_detail.status_code == 404
    assert other_detail.json()["error"]["code"] == "not_found"


async def test_hall_of_fame_returns_structured_seasons_without_telegram_photo_ids(
    player_api_client: tuple[AsyncClient, async_sessionmaker],
) -> None:
    client, session_factory = player_api_client
    await seed_player_api_data(session_factory)

    response = await client.get("/api/v1/hall-of-fame", headers=auth_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["seasons"][0]["season"] == {
        "id": 1,
        "name": "Весна 2026",
        "starts_at": "2026-04-01",
        "ends_at": "2026-06-30",
    }
    assert body["seasons"][0]["champion"]["display_name"] == "Player"
    assert body["seasons"][0]["knockout_leader"]["display_name"] == "Rival"
    assert "telegram-champion-file-id" not in json.dumps(body)
    assert "photo" not in json.dumps(body)


async def test_rewards_are_current_actor_active_rewards_only(
    player_api_client: tuple[AsyncClient, async_sessionmaker],
) -> None:
    client, session_factory = player_api_client
    await seed_player_api_data(session_factory)

    response = await client.get("/api/v1/me/rewards", headers=auth_headers())
    other = await client.get("/api/v1/me/rewards", headers=auth_headers(telegram_id=200))

    assert response.status_code == 200
    assert len(response.json()["items"]) == 1
    reward = response.json()["items"][0]
    assert reward["reward_type"] == "prize_stack_bonus"
    assert reward["chips_amount"] == 40_000
    assert reward["source_place"] == 1
    assert reward["source_tournament_name"] == "Bounty"
    assert reward["issued_at"].startswith("2026-08-20T00:00:00")
    assert reward["valid_through"] == "2026-09-10"
    assert reward["status"] == "active"
    assert other.json()["items"][0]["chips_amount"] == 30_000


async def test_player_api_reuses_foundation_auth_contract(
    player_api_client: tuple[AsyncClient, async_sessionmaker],
) -> None:
    client, session_factory = player_api_client
    await seed_player_api_data(session_factory)

    missing = await client.get("/api/v1/ratings")
    blocked = await client.get("/api/v1/me/profile", headers=auth_headers(telegram_id=300))

    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "unauthorized"
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "forbidden"
