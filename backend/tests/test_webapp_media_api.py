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
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import dependencies
from app.api.media_dependencies import media_read_service
from app.api.v1 import admin_hall_of_fame, admin_tournaments, hall_of_fame, history
from app.common.clock import FixedClock
from app.db.base import Base
from app.db.models import (
    HallOfFamePhoto,
    ScoringConfig,
    Season,
    Tournament,
    TournamentPhoto,
    TournamentResult,
)
from app.db.models.enums import TournamentResultSource, TournamentStatus, UserRole, UserStatus
from app.main import app
from app.services.hall_of_fame_management_service import HallOfFameManagementService
from app.services.media_gateway import MediaContent, MediaGatewayError
from app.services.media_read_service import MediaReadService
from app.services.result_service import ResultService
from app.services.user_access_service import UserAccessService
from app.services.user_statistics_service import UserStatisticsService

TEST_BOT_TOKEN = "123456:test-token"
NOW = datetime(2026, 9, 3, 12, tzinfo=ZoneInfo("Europe/Moscow"))


class FakeMediaGateway:
    def __init__(self) -> None:
        self.requests: list[str] = []
        self.fail = False

    async def download_photo(self, source_reference: str) -> MediaContent:
        self.requests.append(source_reference)
        if self.fail:
            raise MediaGatewayError
        return MediaContent(data=f"bytes:{source_reference}".encode(), content_type="image/jpeg")


def _signed_init_data(telegram_id: int) -> str:
    data = {
        "auth_date": str(int(datetime.now(UTC).timestamp())),
        "query_id": "media-api-test",
        "user": json.dumps(
            {"id": telegram_id, "first_name": "Test"},
            separators=(",", ":"),
        ),
    }
    data_check_string = "\n".join(f"{key}={data[key]}" for key in sorted(data))
    secret_key = hmac.new(b"WebAppData", TEST_BOT_TOKEN.encode(), hashlib.sha256).digest()
    data["hash"] = hmac.new(
        secret_key,
        data_check_string.encode(),
        hashlib.sha256,
    ).hexdigest()
    return urlencode(data)


def _auth_headers(telegram_id: int) -> dict[str, str]:
    return {"Authorization": f"tma {_signed_init_data(telegram_id)}"}


@pytest.fixture
async def media_api_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[AsyncClient, FakeMediaGateway, dict[str, int]]]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'webapp_media.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    clock = FixedClock(NOW)
    gateway = FakeMediaGateway()

    monkeypatch.setattr(dependencies.settings, "telegram_bot_token", TEST_BOT_TOKEN)
    monkeypatch.setattr(dependencies.settings, "telegram_webapp_auth_max_age_seconds", 60)
    monkeypatch.setattr(dependencies, "user_access_service", UserAccessService(session_factory))
    monkeypatch.setattr(
        admin_tournaments,
        "result_service",
        ResultService(session_factory, clock=clock),
    )
    monkeypatch.setattr(
        hall_of_fame,
        "user_statistics_service",
        UserStatisticsService(session_factory, clock=clock),
    )
    monkeypatch.setattr(
        history,
        "user_statistics_service",
        UserStatisticsService(session_factory, clock=clock),
    )
    monkeypatch.setattr(
        admin_hall_of_fame,
        "hall_of_fame_management_service",
        HallOfFameManagementService(session_factory, clock=clock),
    )
    app.dependency_overrides[media_read_service] = lambda: MediaReadService(
        session_factory,
        gateway,
        clock=clock,
    )

    async with session_factory() as session:
        config = ScoringConfig()
        session.add(config)
        await session.flush()
        await seed_tournament_types_async(session)
        public_season = Season(
            name="Public season",
            scoring_config_id=config.id,
            starts_at=date(2026, 1, 1),
            ends_at=date(2026, 6, 30),
        )
        current_season = Season(
            name="Current season",
            scoring_config_id=config.id,
            starts_at=date(2026, 7, 1),
            ends_at=date(2026, 12, 31),
        )
        future_season = Season(
            name="Future season",
            scoring_config_id=config.id,
            starts_at=date(2027, 1, 1),
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
        player = build_player(
            telegram_id=300,
            display_name="Player",
            status=UserStatus.ACTIVE,
        )
        session.add_all([public_season, current_season, future_season, admin, superadmin, player])
        await session.flush()
        tournament = Tournament(
            season_id=current_season.id,
            scoring_config_id=config.id,
            tournament_type_id=tournament_type_id("classic_v2"),
            date=NOW.date(),
            status=TournamentStatus.ACTIVE,
        )
        historical_tournament = Tournament(
            season_id=public_season.id,
            scoring_config_id=config.id,
            tournament_type_id=tournament_type_id("classic_v2"),
            date=date(2026, 6, 20),
            status=TournamentStatus.CLOSED,
            tournament_fund=1000,
        )
        session.add_all([tournament, historical_tournament])
        await session.flush()
        tournament_photos = [
            TournamentPhoto(
                tournament_id=tournament.id,
                telegram_file_id="tournament-file-second",
                telegram_file_unique_id="tournament-unique-second",
                uploaded_by_user_id=admin.id,
                position=1,
            ),
            TournamentPhoto(
                tournament_id=tournament.id,
                telegram_file_id="tournament-file-first",
                telegram_file_unique_id="tournament-unique-first",
                uploaded_by_user_id=admin.id,
                position=0,
            ),
        ]
        hall_photos = [
            HallOfFamePhoto(
                season_id=public_season.id,
                telegram_file_id="hall-file-second",
                telegram_file_unique_id="hall-unique-second",
                uploaded_by_user_id=superadmin.id,
                position=1,
            ),
            HallOfFamePhoto(
                season_id=public_season.id,
                telegram_file_id="hall-file-first",
                telegram_file_unique_id="hall-unique-first",
                uploaded_by_user_id=superadmin.id,
                position=0,
            ),
        ]
        future_photo = HallOfFamePhoto(
            season_id=future_season.id,
            telegram_file_id="future-hall-file",
            telegram_file_unique_id="future-hall-unique",
            uploaded_by_user_id=superadmin.id,
            position=0,
        )
        historical_photo = TournamentPhoto(
            tournament_id=historical_tournament.id,
            telegram_file_id="historical-tournament-file",
            telegram_file_unique_id="historical-tournament-unique",
            uploaded_by_user_id=admin.id,
            position=0,
        )
        session.add_all(
            [
                *tournament_photos,
                *hall_photos,
                future_photo,
                historical_photo,
                TournamentResult(
                    tournament_id=historical_tournament.id,
                    player_id=player.id,
                    source=TournamentResultSource.WALK_IN_EXISTING,
                    place=1,
                ),
            ]
        )
        await session.commit()
        ids = {
            "historical_tournament": historical_tournament.id,
            "historical_tournament_photo": historical_photo.id,
            "tournament_photo": tournament_photos[1].id,
            "hall_photo": hall_photos[1].id,
            "future_hall_photo": future_photo.id,
        }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, gateway, ids
    app.dependency_overrides.pop(media_read_service, None)
    await engine.dispose()


async def test_media_descriptors_are_ordered_and_hide_telegram_references(
    media_api_client: tuple[AsyncClient, FakeMediaGateway, dict[str, int]],
) -> None:
    client, _, ids = media_api_client

    tournament = await client.get(
        "/api/v1/admin/tournaments/1/results",
        headers=_auth_headers(100),
    )
    hall = await client.get("/api/v1/hall-of-fame", headers=_auth_headers(300))
    hall_admin = await client.get(
        "/api/v1/admin/hall-of-fame/seasons/1",
        headers=_auth_headers(200),
    )
    history = await client.get(
        f"/api/v1/me/history/{ids['historical_tournament']}",
        headers=_auth_headers(300),
    )

    assert tournament.status_code == hall.status_code == hall_admin.status_code == 200
    assert history.status_code == 200
    assert tournament.json()["photo_count"] == 2
    assert [item["position"] for item in tournament.json()["photos"]] == [0, 1]
    assert [item["position"] for item in hall.json()["seasons"][0]["photos"]] == [0, 1]
    assert [item["position"] for item in hall_admin.json()["photos"]] == [0, 1]
    assert history.json()["photos"] == [
        {
            "id": ids["historical_tournament_photo"],
            "position": 0,
            "content_url": (
                f"/api/v1/media/tournament-photos/{ids['historical_tournament_photo']}/content"
            ),
        }
    ]
    encoded = json.dumps([tournament.json(), hall.json(), hall_admin.json(), history.json()])
    assert "telegram_file_id" not in encoded
    assert "telegram_file_unique_id" not in encoded
    assert TEST_BOT_TOKEN not in encoded
    assert all(
        item["content_url"].startswith("/api/v1/media/")
        for item in tournament.json()["photos"] + hall.json()["seasons"][0]["photos"]
    )


async def test_authorized_actors_receive_photo_bytes(
    media_api_client: tuple[AsyncClient, FakeMediaGateway, dict[str, int]],
) -> None:
    client, gateway, ids = media_api_client

    tournament = await client.get(
        f"/api/v1/media/tournament-photos/{ids['tournament_photo']}/content",
        headers=_auth_headers(100),
    )
    hall = await client.get(
        f"/api/v1/media/hall-of-fame-photos/{ids['hall_photo']}/content",
        headers=_auth_headers(300),
    )
    historical = await client.get(
        f"/api/v1/media/tournament-photos/{ids['historical_tournament_photo']}/content",
        headers=_auth_headers(300),
    )

    assert tournament.status_code == hall.status_code == historical.status_code == 200
    assert tournament.content == b"bytes:tournament-file-first"
    assert hall.content == b"bytes:hall-file-first"
    assert historical.content == b"bytes:historical-tournament-file"
    assert (
        tournament.headers["content-type"]
        == hall.headers["content-type"]
        == historical.headers["content-type"]
        == "image/jpeg"
    )
    assert tournament.headers["content-disposition"] == "inline"
    assert gateway.requests == [
        "tournament-file-first",
        "hall-file-first",
        "historical-tournament-file",
    ]


async def test_media_content_authorization_and_not_found_are_fail_closed(
    media_api_client: tuple[AsyncClient, FakeMediaGateway, dict[str, int]],
) -> None:
    client, gateway, ids = media_api_client

    forbidden = await client.get(
        f"/api/v1/media/tournament-photos/{ids['tournament_photo']}/content",
        headers=_auth_headers(300),
    )
    future = await client.get(
        f"/api/v1/media/hall-of-fame-photos/{ids['future_hall_photo']}/content",
        headers=_auth_headers(300),
    )
    missing = await client.get(
        "/api/v1/media/tournament-photos/999999/content",
        headers=_auth_headers(100),
    )

    assert forbidden.status_code == future.status_code == missing.status_code == 404
    assert gateway.requests == []


async def test_gateway_failure_returns_controlled_error_without_source_reference(
    media_api_client: tuple[AsyncClient, FakeMediaGateway, dict[str, int]],
) -> None:
    client, gateway, ids = media_api_client
    gateway.fail = True

    response = await client.get(
        f"/api/v1/media/hall-of-fame-photos/{ids['hall_photo']}/content",
        headers=_auth_headers(300),
    )

    assert response.status_code == 502
    assert response.json() == {
        "error": {
            "code": "media_unavailable",
            "message": "Photo is temporarily unavailable",
        }
    }
    assert "hall-file-first" not in response.text
