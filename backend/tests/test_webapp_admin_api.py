import hashlib
import hmac
import json
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import pytest
from conftest import build_player, seed_tournament_types_async, tournament_type_id
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import dependencies
from app.api.v1 import admin_check_in, admin_tournaments
from app.common.clock import FixedClock
from app.db.base import Base
from app.db.models import (
    PlayerReward,
    ScoringConfig,
    Season,
    Tournament,
    TournamentCombination,
    TournamentRegistration,
    TournamentResult,
    User,
)
from app.db.models.enums import (
    TournamentResultSource,
    TournamentStatus,
    UserGender,
    UserRole,
    UserStatus,
)
from app.main import app
from app.services.result_service import ResultService
from app.services.tournament_check_in_service import TournamentCheckInService
from app.services.tournament_combination_service import TournamentCombinationService
from app.services.tournament_participant_service import TournamentParticipantService
from app.services.user_access_service import UserAccessService

TEST_BOT_TOKEN = "123456:test-token"
NOW = datetime(2026, 9, 3, 12, tzinfo=ZoneInfo("Europe/Moscow"))


def signed_init_data(telegram_id: int) -> str:
    data = {
        "auth_date": str(int(datetime.now(UTC).timestamp())),
        "query_id": "admin-api-test",
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
async def admin_api_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[AsyncClient, async_sessionmaker, dict[str, int]]]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'webapp_admin.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    clock = FixedClock(NOW)
    monkeypatch.setattr(dependencies.settings, "telegram_bot_token", TEST_BOT_TOKEN)
    monkeypatch.setattr(dependencies.settings, "telegram_webapp_auth_max_age_seconds", 60)
    monkeypatch.setattr(dependencies, "user_access_service", UserAccessService(session_factory))
    monkeypatch.setattr(
        admin_tournaments,
        "result_service",
        ResultService(session_factory, clock=clock),
    )
    monkeypatch.setattr(
        admin_tournaments,
        "tournament_combination_service",
        TournamentCombinationService(session_factory, clock=clock),
    )
    monkeypatch.setattr(
        admin_check_in,
        "tournament_check_in_service",
        TournamentCheckInService(session_factory, clock=clock),
    )
    monkeypatch.setattr(
        admin_check_in,
        "tournament_participant_service",
        TournamentParticipantService(session_factory, clock=clock),
    )

    async with session_factory() as session:
        config = ScoringConfig()
        session.add(config)
        await session.flush()
        await seed_tournament_types_async(session)
        season = Season(
            name="Осень 2026",
            scoring_config_id=config.id,
            starts_at=date(2026, 9, 1),
            ends_at=None,
        )
        admin = build_player(
            telegram_id=100,
            display_name="Admin",
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
        superadmin = build_player(
            telegram_id=200,
            display_name="Superadmin",
            role=UserRole.SUPERADMIN,
            status=UserStatus.ACTIVE,
        )
        player_actor = build_player(
            telegram_id=300,
            display_name="Player actor",
            status=UserStatus.ACTIVE,
        )
        participant = build_player(
            telegram_id=400,
            display_name="Participant",
            status=UserStatus.ACTIVE,
        )
        registered = build_player(
            telegram_id=500,
            display_name="Registered",
            gender=UserGender.FEMALE,
            status=UserStatus.ACTIVE,
        )
        unknown_gender = build_player(
            telegram_id=600,
            display_name="Unknown Gender",
            status=UserStatus.ACTIVE,
        )
        session.add_all(
            [
                season,
                admin,
                superadmin,
                player_actor,
                participant,
                registered,
                unknown_gender,
            ]
        )
        await session.flush()
        tournament = Tournament(
            season_id=season.id,
            scoring_config_id=config.id,
            tournament_type_id=tournament_type_id("classic_v2"),
            date=NOW.date(),
            status=TournamentStatus.ACTIVE,
        )
        session.add(tournament)
        reward_source = Tournament(
            season_id=season.id,
            scoring_config_id=config.id,
            tournament_type_id=tournament_type_id("classic_v2"),
            date=date(2026, 9, 2),
            status=TournamentStatus.CLOSED,
            tournament_fund=1000,
        )
        session.add(reward_source)
        await session.flush()
        result = TournamentResult(
            tournament_id=tournament.id,
            player_id=participant.id,
            source=TournamentResultSource.WALK_IN_EXISTING,
        )
        session.add(result)
        session.add(
            TournamentRegistration(
                tournament_id=tournament.id,
                player_id=registered.id,
            )
        )
        reward = PlayerReward(
            player_id=registered.id,
            chips_amount=40_000,
            source_tournament_id=reward_source.id,
            source_place=1,
            issued_at=datetime(2026, 9, 2, 12, tzinfo=ZoneInfo("Europe/Moscow")),
            valid_through=date(2026, 9, 9),
        )
        session.add(reward)
        await session.commit()
        ids = {
            "tournament_id": tournament.id,
            "participant_id": participant.id,
            "registered_id": registered.id,
            "unknown_gender_id": unknown_gender.id,
            "reward_id": reward.id,
        }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, session_factory, ids
    await engine.dispose()


async def test_admin_can_read_and_persist_result_update(
    admin_api_client: tuple[AsyncClient, async_sessionmaker, dict[str, int]],
) -> None:
    client, session_factory, ids = admin_api_client

    listed = await client.get("/api/v1/admin/tournaments", headers=auth_headers(100))
    updated = await client.patch(
        f"/api/v1/admin/tournaments/{ids['tournament_id']}/results/{ids['participant_id']}",
        headers=auth_headers(100),
        json={"field": "place", "value": 1},
    )

    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [ids["tournament_id"]]
    assert updated.status_code == 200
    assert updated.json()["players"][0]["place"] == 1
    async with session_factory() as session:
        result = await session.scalar(
            select(TournamentResult).where(
                TournamentResult.tournament_id == ids["tournament_id"],
                TournamentResult.player_id == ids["participant_id"],
            )
        )
        assert result is not None
        assert result.place == 1


async def test_player_is_denied_admin_tournament_operations(
    admin_api_client: tuple[AsyncClient, async_sessionmaker, dict[str, int]],
) -> None:
    client, _, ids = admin_api_client

    response = await client.get(
        f"/api/v1/admin/tournaments/{ids['tournament_id']}/results",
        headers=auth_headers(300),
    )

    assert response.status_code == 403
    assert response.json() == {"error": {"code": "forbidden", "message": "Admin access required"}}


async def test_superadmin_has_admin_result_access(
    admin_api_client: tuple[AsyncClient, async_sessionmaker, dict[str, int]],
) -> None:
    client, _, ids = admin_api_client

    response = await client.get(
        f"/api/v1/admin/tournaments/{ids['tournament_id']}/results",
        headers=auth_headers(200),
    )

    assert response.status_code == 200
    assert response.json()["tournament"]["id"] == ids["tournament_id"]


async def test_admin_combination_occurrences_are_independent(
    admin_api_client: tuple[AsyncClient, async_sessionmaker, dict[str, int]],
) -> None:
    client, session_factory, ids = admin_api_client
    path = f"/api/v1/admin/tournaments/{ids['tournament_id']}/combinations"
    payload = {
        "player_id": ids["participant_id"],
        "combination_type": "four_of_a_kind",
        "rank": "A",
    }

    first = await client.post(path, headers=auth_headers(100), json=payload)
    second = await client.post(path, headers=auth_headers(100), json=payload)

    assert first.status_code == 201
    assert second.status_code == 201
    combinations = second.json()["combinations"]
    assert len(combinations) == 2
    assert len({item["id"] for item in combinations}) == 2

    deleted = await client.delete(
        f"{path}/{combinations[0]['id']}",
        headers=auth_headers(100),
    )
    assert deleted.status_code == 200
    assert [item["id"] for item in deleted.json()["combinations"]] == [combinations[1]["id"]]
    async with session_factory() as session:
        stored = list((await session.scalars(select(TournamentCombination))).all())
        assert [item.id for item in stored] == [combinations[1]["id"]]


async def test_admin_combination_validation_and_not_found_errors(
    admin_api_client: tuple[AsyncClient, async_sessionmaker, dict[str, int]],
) -> None:
    client, _, ids = admin_api_client
    path = f"/api/v1/admin/tournaments/{ids['tournament_id']}/combinations"

    invalid = await client.post(
        path,
        headers=auth_headers(100),
        json={
            "player_id": ids["participant_id"],
            "combination_type": "four_of_a_kind",
            "rank": "1",
        },
    )
    missing_player = await client.post(
        path,
        headers=auth_headers(100),
        json={
            "player_id": 999,
            "combination_type": "royal_flush",
            "rank": None,
        },
    )

    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "validation_error"
    assert missing_player.status_code == 404
    assert missing_player.json()["error"]["code"] == "not_found"


async def test_admin_check_in_read_and_registered_player_mutation(
    admin_api_client: tuple[AsyncClient, async_sessionmaker, dict[str, int]],
) -> None:
    client, session_factory, ids = admin_api_client
    base = f"/api/v1/admin/tournaments/{ids['tournament_id']}"

    state = await client.get(f"{base}/check-in", headers=auth_headers(100))
    completed = await client.post(
        f"{base}/check-ins",
        headers=auth_headers(100),
        json={
            "kind": "existing",
            "player_id": ids["registered_id"],
            "gender_decision": "keep",
            "reward_id": None,
        },
    )

    assert state.status_code == 200
    assert state.json()["registered_count"] == 1
    assert [item["user_id"] for item in state.json()["registered_candidates"]] == [
        ids["registered_id"]
    ]
    assert completed.status_code == 201
    assert completed.json()["created"] is True
    async with session_factory() as session:
        result = await session.scalar(
            select(TournamentResult).where(
                TournamentResult.tournament_id == ids["tournament_id"],
                TournamentResult.player_id == ids["registered_id"],
            )
        )
        assert result is not None
        assert result.source == TournamentResultSource.REGISTERED
        assert await session.scalar(
            select(TournamentRegistration.id).where(
                TournamentRegistration.tournament_id == ids["tournament_id"],
                TournamentRegistration.player_id == ids["registered_id"],
            )
        )


async def test_superadmin_check_in_redeems_reward_once_through_shared_contract(
    admin_api_client: tuple[AsyncClient, async_sessionmaker, dict[str, int]],
) -> None:
    client, session_factory, ids = admin_api_client
    base = f"/api/v1/admin/tournaments/{ids['tournament_id']}"

    decision = await client.get(
        f"{base}/check-in/players/{ids['registered_id']}/decision",
        headers=auth_headers(200),
    )
    first = await client.post(
        f"{base}/check-ins",
        headers=auth_headers(200),
        json={
            "kind": "existing",
            "player_id": ids["registered_id"],
            "gender_decision": "keep",
            "reward_id": ids["reward_id"],
        },
    )
    repeated = await client.post(
        f"{base}/check-ins",
        headers=auth_headers(200),
        json={
            "kind": "existing",
            "player_id": ids["registered_id"],
            "gender_decision": "keep",
            "reward_id": ids["reward_id"],
        },
    )

    assert decision.status_code == 200
    assert [item["id"] for item in decision.json()["active_rewards"]] == [ids["reward_id"]]
    assert first.status_code == 201
    assert first.json()["created"] is True
    assert repeated.status_code == 201
    assert repeated.json()["created"] is False
    async with session_factory() as session:
        reward = await session.get(PlayerReward, ids["reward_id"])
        results = list(
            (
                await session.execute(
                    select(TournamentResult).where(
                        TournamentResult.tournament_id == ids["tournament_id"],
                        TournamentResult.player_id == ids["registered_id"],
                    )
                )
            ).scalars()
        )
        assert reward is not None
        assert reward.redeemed_tournament_id == ids["tournament_id"]
        assert len(results) == 1


async def test_existing_walk_in_gender_and_check_in_are_persisted_together(
    admin_api_client: tuple[AsyncClient, async_sessionmaker, dict[str, int]],
) -> None:
    client, session_factory, ids = admin_api_client

    response = await client.post(
        f"/api/v1/admin/tournaments/{ids['tournament_id']}/check-ins",
        headers=auth_headers(100),
        json={
            "kind": "existing",
            "player_id": ids["unknown_gender_id"],
            "gender_decision": "male",
        },
    )

    assert response.status_code == 201
    assert response.json()["player"]["gender"] == "male"
    async with session_factory() as session:
        user = await session.get(User, ids["unknown_gender_id"])
        result = await session.scalar(
            select(TournamentResult).where(
                TournamentResult.tournament_id == ids["tournament_id"],
                TournamentResult.player_id == ids["unknown_gender_id"],
            )
        )
        assert user is not None
        assert user.gender == UserGender.MALE
        assert result is not None
        assert result.source == TournamentResultSource.WALK_IN_EXISTING


async def test_new_walk_in_is_explicit_and_atomic(
    admin_api_client: tuple[AsyncClient, async_sessionmaker, dict[str, int]],
) -> None:
    client, session_factory, ids = admin_api_client

    response = await client.post(
        f"/api/v1/admin/tournaments/{ids['tournament_id']}/check-ins",
        headers=auth_headers(100),
        json={"kind": "new", "display_name": "New Walk In", "gender": "female"},
    )

    assert response.status_code == 201
    assert response.json()["player"]["display_name"] == "New Walk In"
    assert response.json()["player"]["gender"] == "female"
    async with session_factory() as session:
        user = await session.scalar(select(User).where(User.display_name == "New Walk In"))
        assert user is not None
        result = await session.scalar(
            select(TournamentResult).where(
                TournamentResult.tournament_id == ids["tournament_id"],
                TournamentResult.player_id == user.id,
            )
        )
        assert result is not None
        assert result.source == TournamentResultSource.WALK_IN_NEW


async def test_check_in_requires_gender_decision_and_denies_player(
    admin_api_client: tuple[AsyncClient, async_sessionmaker, dict[str, int]],
) -> None:
    client, _, ids = admin_api_client
    path = f"/api/v1/admin/tournaments/{ids['tournament_id']}/check-ins"
    payload = {
        "kind": "existing",
        "player_id": ids["unknown_gender_id"],
        "gender_decision": "keep",
    }

    missing_decision = await client.post(path, headers=auth_headers(100), json=payload)
    denied = await client.post(path, headers=auth_headers(300), json=payload)
    already_set = await client.post(
        path,
        headers=auth_headers(100),
        json={
            "kind": "existing",
            "player_id": ids["registered_id"],
            "gender_decision": "male",
        },
    )
    missing_player = await client.post(
        path,
        headers=auth_headers(100),
        json={"kind": "existing", "player_id": 999, "gender_decision": "keep"},
    )

    assert missing_decision.status_code == 422
    assert missing_decision.json()["error"]["code"] == "validation_error"
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "forbidden"
    assert already_set.status_code == 409
    assert already_set.json()["error"]["code"] == "conflict"
    assert missing_player.status_code == 404
    assert missing_player.json()["error"]["code"] == "not_found"


async def test_superadmin_can_remove_open_tournament_participant(
    admin_api_client: tuple[AsyncClient, async_sessionmaker, dict[str, int]],
) -> None:
    client, session_factory, ids = admin_api_client
    path = f"/api/v1/admin/tournaments/{ids['tournament_id']}/participants/{ids['participant_id']}"

    admin_denied = await client.delete(path, headers=auth_headers(100))
    removed = await client.delete(path, headers=auth_headers(200))

    assert admin_denied.status_code == 403
    assert removed.status_code == 200
    assert removed.json()["player_id"] == ids["participant_id"]
    async with session_factory() as session:
        result = await session.scalar(
            select(TournamentResult).where(
                TournamentResult.tournament_id == ids["tournament_id"],
                TournamentResult.player_id == ids["participant_id"],
            )
        )
        assert result is None


async def test_admin_can_add_existing_and_new_open_tournament_participants(
    admin_api_client: tuple[AsyncClient, async_sessionmaker, dict[str, int]],
) -> None:
    client, session_factory, ids = admin_api_client
    path = f"/api/v1/admin/tournaments/{ids['tournament_id']}/participants"

    existing = await client.post(
        path,
        headers=auth_headers(100),
        json={"kind": "existing", "player_id": ids["unknown_gender_id"]},
    )
    new = await client.post(
        path,
        headers=auth_headers(100),
        json={"kind": "new", "display_name": "Historical Walk In"},
    )

    assert existing.status_code == 201
    assert new.status_code == 201
    async with session_factory() as session:
        created_user = await session.scalar(
            select(User).where(User.display_name == "Historical Walk In")
        )
        assert created_user is not None
        results = list(
            (
                await session.execute(
                    select(TournamentResult).where(
                        TournamentResult.tournament_id == ids["tournament_id"],
                        TournamentResult.player_id.in_([ids["unknown_gender_id"], created_user.id]),
                    )
                )
            ).scalars()
        )
        assert {result.player_id for result in results} == {
            ids["unknown_gender_id"],
            created_user.id,
        }
