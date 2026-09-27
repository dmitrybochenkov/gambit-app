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
    seed_weekly_templates_async,
    tournament_type_id,
)
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import dependencies
from app.api.v1 import (
    admin_check_in,
    admin_planning,
    admin_seasons,
    admin_tournament_close,
    admin_tournaments,
)
from app.common.clock import FixedClock
from app.db.base import Base
from app.db.models import (
    PlayerReward,
    ScoringConfig,
    Season,
    Tournament,
    TournamentCombination,
    TournamentPhoto,
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
from app.services.closed_tournament_correction_service import ClosedTournamentCorrectionService
from app.services.result_service import ResultService
from app.services.season_service import SeasonService
from app.services.tournament_check_in_service import TournamentCheckInService
from app.services.tournament_combination_service import TournamentCombinationService
from app.services.tournament_participant_service import TournamentParticipantService
from app.services.tournament_planning_service import TournamentPlanningService
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
        admin_tournament_close,
        "result_service",
        ResultService(session_factory, clock=clock),
    )
    monkeypatch.setattr(
        admin_tournament_close,
        "closed_tournament_correction_service",
        ClosedTournamentCorrectionService(session_factory, clock=clock),
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
    monkeypatch.setattr(
        admin_planning,
        "tournament_planning_service",
        TournamentPlanningService(session_factory, clock=clock),
    )
    monkeypatch.setattr(
        admin_seasons,
        "season_service",
        SeasonService(session_factory, clock=clock),
    )

    async with session_factory() as session:
        config = ScoringConfig()
        session.add(config)
        await session.flush()
        await seed_tournament_types_async(session)
        await seed_tournament_configs_async(session)
        await seed_tournament_rules_async(session)
        await seed_weekly_templates_async(session)
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


async def test_superadmin_close_and_correction_use_shared_application_contracts(
    admin_api_client: tuple[AsyncClient, async_sessionmaker, dict[str, int]],
) -> None:
    client, session_factory, ids = admin_api_client
    tournament_id = ids["tournament_id"]
    async with session_factory() as session:
        result = await session.scalar(
            select(TournamentResult).where(
                TournamentResult.tournament_id == tournament_id,
                TournamentResult.player_id == ids["participant_id"],
            )
        )
        assert result is not None
        result.place = 1
        session.add(
            TournamentPhoto(
                tournament_id=tournament_id,
                telegram_file_id="photo",
                telegram_file_unique_id="photo-unique",
                uploaded_by_user_id=None,
                position=0,
            )
        )
        await session.commit()

    readiness = await client.get(
        f"/api/v1/admin/tournaments/{tournament_id}/close-readiness",
        headers=auth_headers(200),
    )
    preview = await client.post(
        f"/api/v1/admin/tournaments/{tournament_id}/close-preview",
        headers=auth_headers(200),
        json={"tournament_fund": 1000},
    )
    closed = await client.post(
        f"/api/v1/admin/tournaments/{tournament_id}/close",
        headers=auth_headers(200),
        json={"tournament_fund": 1000},
    )

    assert readiness.status_code == 200
    assert readiness.json()["is_ready"] is True
    assert preview.status_code == 200
    assert preview.json()["results"]["players"][0]["tournament_points"] == "450.00"
    assert closed.status_code == 200
    assert len(closed.json()["newly_issued_rewards"]) == 1

    started = await client.get(
        f"/api/v1/admin/tournaments/{tournament_id}/correction",
        headers=auth_headers(200),
    )
    assert started.status_code == 200
    draft = started.json()["draft"]
    draft["proposed_tournament_fund"] = 2000
    draft["proposed_results"][0]["display_name"] = "Client supplied name"
    correction_preview = await client.post(
        f"/api/v1/admin/tournaments/{tournament_id}/correction-preview",
        headers=auth_headers(200),
        json=draft,
    )
    applied = await client.post(
        f"/api/v1/admin/tournaments/{tournament_id}/correction",
        headers=auth_headers(200),
        json=draft,
    )
    stale = await client.post(
        f"/api/v1/admin/tournaments/{tournament_id}/correction",
        headers=auth_headers(200),
        json=draft,
    )

    assert correction_preview.status_code == 200
    assert correction_preview.json()["fund_after"] == 2000
    assert correction_preview.json()["after_results"]["players"][0]["display_name"] == "Participant"
    assert applied.status_code == 200
    assert applied.json()["after_results"]["tournament_fund"] == 2000
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "conflict"
    async with session_factory() as session:
        tournament = await session.get(Tournament, tournament_id)
        result = await session.scalar(
            select(TournamentResult).where(TournamentResult.tournament_id == tournament_id)
        )
        rewards = list(
            (
                await session.scalars(
                    select(PlayerReward).where(PlayerReward.source_tournament_id == tournament_id)
                )
            ).all()
        )
        assert tournament is not None
        assert tournament.status == TournamentStatus.CLOSED
        assert tournament.tournament_fund == 2000
        assert result is not None
        assert result.tournament_points == 900
        assert len(rewards) == 1

    repeated_close = await client.post(
        f"/api/v1/admin/tournaments/{tournament_id}/close",
        headers=auth_headers(200),
        json={"tournament_fund": 3000},
    )
    assert repeated_close.status_code == 409


async def test_correction_rejects_tampered_result_identity(
    admin_api_client: tuple[AsyncClient, async_sessionmaker, dict[str, int]],
) -> None:
    client, session_factory, ids = admin_api_client
    tournament_id = ids["tournament_id"]
    async with session_factory() as session:
        tournament = await session.get(Tournament, tournament_id)
        assert tournament is not None
        tournament.status = TournamentStatus.CLOSED
        tournament.tournament_fund = 1000
        await session.commit()

    started = await client.get(
        f"/api/v1/admin/tournaments/{tournament_id}/correction",
        headers=auth_headers(200),
    )
    draft = started.json()["draft"]
    draft["proposed_results"][0]["result_id"] = 99999

    response = await client.post(
        f"/api/v1/admin/tournaments/{tournament_id}/correction-preview",
        headers=auth_headers(200),
        json=draft,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


async def test_close_and_correction_preserve_superadmin_policy(
    admin_api_client: tuple[AsyncClient, async_sessionmaker, dict[str, int]],
) -> None:
    client, _, ids = admin_api_client
    path = f"/api/v1/admin/tournaments/{ids['tournament_id']}/close-readiness"

    admin = await client.get(path, headers=auth_headers(100))
    player = await client.get(path, headers=auth_headers(300))

    assert admin.status_code == 403
    assert player.status_code == 403


async def test_superadmin_planning_create_edit_approve_and_delete(
    admin_api_client: tuple[AsyncClient, async_sessionmaker, dict[str, int]],
) -> None:
    client, session_factory, ids = admin_api_client
    base = "/api/v1/admin/planning"
    target_date = date(2026, 9, 10)
    original_type_id = tournament_type_id("classic_v3")
    replacement_type_id = tournament_type_id("bounty_v3")

    month = await client.get(
        f"{base}/calendar?year=2026&month=9",
        headers=auth_headers(200),
    )
    types = await client.get(f"{base}/tournament-types", headers=auth_headers(200))
    preview = await client.post(
        f"{base}/tournaments/preview",
        headers=auth_headers(200),
        json={"tournament_date": target_date.isoformat(), "tournament_type_id": original_type_id},
    )
    created = await client.post(
        f"{base}/tournaments",
        headers=auth_headers(200),
        json={"tournament_date": target_date.isoformat(), "tournament_type_id": original_type_id},
    )
    duplicate = await client.post(
        f"{base}/tournaments",
        headers=auth_headers(200),
        json={"tournament_date": target_date.isoformat(), "tournament_type_id": original_type_id},
    )

    assert month.status_code == 200
    assert types.status_code == 200
    assert preview.status_code == 200
    assert created.status_code == 200
    assert created.json()["registration_open"] is False
    assert duplicate.status_code == 409
    tournament_id = created.json()["id"]

    changed = await client.patch(
        f"{base}/tournaments/{tournament_id}/type",
        headers=auth_headers(200),
        json={"tournament_type_id": replacement_type_id},
    )
    assert changed.status_code == 200
    assert changed.json()["tournament_type_code"] == "bounty_v3"
    assert changed.json()["date"] == target_date.isoformat()
    assert changed.json()["registration_open"] is False

    row_number = next(
        week["row_number"]
        for week in month.json()["weeks"]
        if any(day["date"] == target_date.isoformat() for day in week["days"])
    )
    approval_preview = await client.post(
        f"{base}/weeks/approval-preview",
        headers=auth_headers(200),
        json={"year": 2026, "month": 9, "row_number": row_number},
    )
    approved = await client.post(
        f"{base}/weeks/approve",
        headers=auth_headers(200),
        json={"year": 2026, "month": 9, "row_number": row_number},
    )
    assert approval_preview.status_code == 200
    assert approved.status_code == 200
    assert approved.json()["tournaments"][0]["registration_open"] is True

    async with session_factory() as session:
        session.add(
            TournamentRegistration(
                tournament_id=tournament_id,
                player_id=ids["participant_id"],
            )
        )
        await session.commit()

    delete_preview = await client.get(
        f"{base}/tournaments/{tournament_id}/delete-preview",
        headers=auth_headers(200),
    )
    deleted = await client.delete(
        f"{base}/tournaments/{tournament_id}",
        headers=auth_headers(200),
    )
    assert delete_preview.status_code == 200
    assert delete_preview.json()["registrations_count"] == 1
    assert deleted.status_code == 200
    assert [item["telegram_id"] for item in deleted.json()["cancellation_notifications"]] == [400]
    async with session_factory() as session:
        assert await session.get(Tournament, tournament_id) is None
        registration = await session.scalar(
            select(TournamentRegistration).where(
                TournamentRegistration.tournament_id == tournament_id
            )
        )
        assert registration is None


async def test_superadmin_planning_autofill_and_role_policy(
    admin_api_client: tuple[AsyncClient, async_sessionmaker, dict[str, int]],
) -> None:
    client, session_factory, _ids = admin_api_client
    base = "/api/v1/admin/planning"
    month = await client.get(
        f"{base}/calendar?year=2026&month=9",
        headers=auth_headers(200),
    )
    row_number = next(
        week["row_number"]
        for week in month.json()["weeks"]
        if any(day["date"] == "2026-09-16" for day in week["days"])
    )
    payload = {"year": 2026, "month": 9, "row_number": row_number}

    admin_denied = await client.post(
        f"{base}/weeks/autofill-preview",
        headers=auth_headers(100),
        json=payload,
    )
    player_denied = await client.get(
        f"{base}/calendar?year=2026&month=9",
        headers=auth_headers(300),
    )
    preview = await client.post(
        f"{base}/weeks/autofill-preview",
        headers=auth_headers(200),
        json=payload,
    )
    applied = await client.post(
        f"{base}/weeks/autofill",
        headers=auth_headers(200),
        json=payload,
    )
    repeated = await client.post(
        f"{base}/weeks/autofill",
        headers=auth_headers(200),
        json=payload,
    )

    assert admin_denied.status_code == 403
    assert player_denied.status_code == 403
    assert preview.status_code == 200
    assert len(preview.json()["tournaments"]) == 5
    assert applied.status_code == 200
    assert len(applied.json()["tournaments"]) == 5
    assert repeated.status_code == 409
    async with session_factory() as session:
        tournaments = list(
            (
                await session.scalars(
                    select(Tournament).where(
                        Tournament.date.between(date(2026, 9, 16), date(2026, 9, 20))
                    )
                )
            ).all()
        )
    assert len(tournaments) == 5
    assert all(not item.registration_open for item in tournaments)


async def test_superadmin_season_timeline_create_and_delete_use_shared_contract(
    admin_api_client: tuple[AsyncClient, async_sessionmaker, dict[str, int]],
) -> None:
    client, session_factory, _ids = admin_api_client
    base = "/api/v1/admin/seasons"
    command = {"name": "Зима 2026", "starts_at": "2026-10-01"}

    initial = await client.get(base, headers=auth_headers(200))
    absent_delete_preview = await client.get(
        f"{base}/future/delete-preview",
        headers=auth_headers(200),
    )
    absent_delete = await client.request(
        "DELETE",
        f"{base}/future",
        headers=auth_headers(200),
        json={"expected_season_id": 999},
    )
    preview = await client.post(
        f"{base}/next/preview",
        headers=auth_headers(200),
        json=command,
    )
    created = await client.post(f"{base}/next", headers=auth_headers(200), json=command)
    repeated = await client.post(f"{base}/next", headers=auth_headers(200), json=command)
    stale = await client.request(
        "DELETE",
        f"{base}/future",
        headers=auth_headers(200),
        json={"expected_season_id": created.json()["id"] + 999},
    )
    delete_preview = await client.get(
        f"{base}/future/delete-preview",
        headers=auth_headers(200),
    )
    deleted = await client.request(
        "DELETE",
        f"{base}/future",
        headers=auth_headers(200),
        json={"expected_season_id": created.json()["id"]},
    )

    assert initial.status_code == 200
    assert initial.json()["can_create_next_season"] is True
    assert absent_delete_preview.status_code == 404
    assert absent_delete.status_code == 404
    assert preview.status_code == 200
    assert preview.json()["active_season_ends_at"] == "2026-09-30"
    assert created.status_code == 200
    assert (
        created.json()["scoring_config_id"] == initial.json()["current_season"]["scoring_config_id"]
    )
    assert repeated.status_code == 409
    assert stale.status_code == 409
    assert delete_preview.status_code == 200
    assert delete_preview.json()["future_season"]["id"] == created.json()["id"]
    assert delete_preview.json()["previous_season"]["ends_at"] == "2026-09-30"
    assert deleted.status_code == 200
    assert deleted.json()["future_season"] is None
    assert deleted.json()["current_season"]["ends_at"] is None

    async with session_factory() as session:
        seasons = list((await session.scalars(select(Season).order_by(Season.starts_at))).all())
    assert [(item.name, item.ends_at) for item in seasons] == [("Осень 2026", None)]


async def test_superadmin_season_delete_rejects_referenced_future_and_stale_state(
    admin_api_client: tuple[AsyncClient, async_sessionmaker, dict[str, int]],
) -> None:
    client, session_factory, _ids = admin_api_client
    base = "/api/v1/admin/seasons"
    command = {"name": "Зима 2026", "starts_at": "2026-10-01"}
    created = await client.post(f"{base}/next", headers=auth_headers(200), json=command)
    future_id = created.json()["id"]

    async with session_factory() as session:
        current = await session.scalar(select(Season).where(Season.name == "Осень 2026"))
        assert current is not None
        session.add(
            Tournament(
                season_id=future_id,
                scoring_config_id=created.json()["scoring_config_id"],
                tournament_type_id=tournament_type_id("classic_v3"),
                date=date(2026, 10, 2),
                status=TournamentStatus.ACTIVE,
            )
        )
        await session.commit()

    preview = await client.get(
        f"{base}/future/delete-preview",
        headers=auth_headers(200),
    )
    rejected = await client.request(
        "DELETE",
        f"{base}/future",
        headers=auth_headers(200),
        json={"expected_season_id": future_id},
    )
    assert preview.status_code == 409
    assert rejected.status_code == 409
    async with session_factory() as session:
        current = await session.scalar(select(Season).where(Season.name == "Осень 2026"))
        future = await session.get(Season, future_id)
    assert current is not None and current.ends_at == date(2026, 9, 30)
    assert future is not None


async def test_season_management_preserves_superadmin_policy_and_validates_dates(
    admin_api_client: tuple[AsyncClient, async_sessionmaker, dict[str, int]],
) -> None:
    client, _session_factory, _ids = admin_api_client
    base = "/api/v1/admin/seasons"

    admin_denied = await client.get(base, headers=auth_headers(100))
    player_denied = await client.get(base, headers=auth_headers(300))
    invalid_date = await client.post(
        f"{base}/next/preview",
        headers=auth_headers(200),
        json={"name": "Сегодня", "starts_at": "2026-09-03"},
    )

    assert admin_denied.status_code == 403
    assert player_denied.status_code == 403
    assert invalid_date.status_code == 422
