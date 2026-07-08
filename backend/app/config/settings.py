from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    app_name: str = "Gambit App"
    app_host: str = "127.0.0.1"
    app_port: int = 8100
    debug: bool = False
    public_base_url: str = ""

    data_dir: str = "../data"
    logs_dir: str = "../logs"
    webapp_dir: str = "../webapp"
    site_dir: str = "../site"
    database_url: str = ""
    telegram_bot_token: str = ""
    telegram_webhook_secret: str = ""
    admin_calendar_checks_enabled: bool = True
    admin_calendar_check_interval_seconds: int = 21_600

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @staticmethod
    def _resolve_path(value: str) -> Path:
        path = Path(value).expanduser()
        if path.is_absolute():
            return path
        return (BACKEND_ROOT / path).resolve()

    @property
    def resolved_data_dir(self) -> Path:
        return self._resolve_path(self.data_dir)

    @property
    def resolved_logs_dir(self) -> Path:
        return self._resolve_path(self.logs_dir)

    @property
    def resolved_webapp_dir(self) -> Path:
        return self._resolve_path(self.webapp_dir)

    @property
    def resolved_site_dir(self) -> Path:
        return self._resolve_path(self.site_dir)

    @property
    def effective_public_base_url(self) -> str:
        return self.public_base_url.strip().rstrip("/")

    @property
    def effective_database_url(self) -> str:
        configured = self.database_url.strip()
        if configured:
            return configured
        database_path = self.resolved_data_dir / "gambit.db"
        return f"sqlite+aiosqlite:///{database_path.as_posix()}"

    @property
    def effective_sync_database_url(self) -> str:
        return self.effective_database_url.replace("+aiosqlite", "")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
