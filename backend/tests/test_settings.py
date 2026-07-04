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
