import pytest

from app.config.settings import BACKEND_ROOT, Settings


def test_standard_project_paths() -> None:
    settings = Settings(
        _env_file=None,
        data_dir="../data",
        logs_dir="../logs",
        webapp_dir="../webapp",
        site_dir="../site",
        database_url="",
    )
    project_root = BACKEND_ROOT.parent

    assert settings.resolved_data_dir == project_root / "data"
    assert settings.resolved_logs_dir == project_root / "logs"
    assert settings.resolved_webapp_dir == project_root / "webapp"
    assert settings.resolved_site_dir == project_root / "site"
    assert settings.effective_database_url == (
        f"sqlite+aiosqlite:///{(project_root / 'data/gambit.db').as_posix()}"
    )


def test_telegram_publication_destinations_are_optional() -> None:
    empty = Settings(
        _env_file=None,
        telegram_club_chat_id="",
        telegram_club_channel_id=" ",
    )
    configured = Settings(
        _env_file=None,
        telegram_club_chat_id="-1001",
        telegram_club_channel_id="-1002",
    )

    assert empty.telegram_club_chat_id is None
    assert empty.telegram_club_channel_id is None
    assert configured.telegram_club_chat_id == -1001
    assert configured.telegram_club_channel_id == -1002


def test_tournament_day_start_hour_defaults_to_11() -> None:
    settings = Settings(_env_file=None)

    assert settings.tournament_day_start_hour == 11
    assert settings.telegram_webapp_auth_max_age_seconds == 86_400


def test_tournament_day_start_hour_must_be_valid() -> None:
    with pytest.raises(ValueError):
        Settings(_env_file=None, tournament_day_start_hour=-1)
    with pytest.raises(ValueError):
        Settings(_env_file=None, tournament_day_start_hour=24)


def test_telegram_webapp_auth_max_age_must_be_positive() -> None:
    with pytest.raises(ValueError):
        Settings(_env_file=None, telegram_webapp_auth_max_age_seconds=0)
