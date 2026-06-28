from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Gambit App"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    debug: bool = False

    database_url: str = "sqlite+aiosqlite:///./gambit.db"
    telegram_bot_token: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
