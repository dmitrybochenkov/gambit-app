from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    app_name: str = "Gambit App"
    app_host: str = "127.0.0.1"
    app_port: int = 8100
    debug: bool = False
    public_base_url: str = ""
    club_timezone: str = "Europe/Moscow"
    tournament_day_start_hour: int = 11
    reward_reminder_run_hour: int = 12

    data_dir: str = "../data"
    logs_dir: str = "../logs"
    webapp_dir: str = "../webapp"
    site_dir: str = "../site"
    database_url: str = ""
    telegram_bot_token: str = ""
    telegram_webhook_secret: str = ""
    telegram_webapp_auth_max_age_seconds: int = 86_400
    telegram_club_chat_id: int | None = None
    telegram_club_channel_id: int | None = None

    @field_validator("telegram_club_chat_id", "telegram_club_channel_id", mode="before")
    @classmethod
    def _empty_telegram_destination_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("tournament_day_start_hour")
    @classmethod
    def _tournament_day_start_hour_is_valid(cls, value: int) -> int:
        if not 0 <= value <= 23:
            raise ValueError("tournament_day_start_hour must be between 0 and 23")
        return value

    @field_validator("reward_reminder_run_hour")
    @classmethod
    def _reward_reminder_run_hour_is_valid(cls, value: int) -> int:
        if not 0 <= value <= 23:
            raise ValueError("reward_reminder_run_hour must be between 0 and 23")
        return value

    @field_validator("telegram_webapp_auth_max_age_seconds")
    @classmethod
    def _telegram_webapp_auth_max_age_seconds_is_valid(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("telegram_webapp_auth_max_age_seconds must be positive")
        return value

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
