import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import parse_qsl

from app.common.clock import Clock, club_clock

WEBAPP_AUTH_SCHEME = "tma"
WEBAPP_AUTH_FUTURE_SKEW_SECONDS = 60


class TelegramWebAppAuthError(ValueError):
    pass


@dataclass(frozen=True)
class TelegramWebAppIdentity:
    telegram_id: int


class TelegramWebAppInitDataVerifier:
    def __init__(
        self,
        *,
        bot_token: str,
        max_age_seconds: int,
        clock: Clock = club_clock,
    ) -> None:
        self.bot_token = bot_token
        self.max_age_seconds = max_age_seconds
        self.clock = clock

    def verify(self, raw_init_data: str) -> TelegramWebAppIdentity:
        if not self.bot_token:
            raise TelegramWebAppAuthError("Telegram bot token is not configured")
        try:
            pairs = parse_qsl(raw_init_data, keep_blank_values=True, strict_parsing=True)
        except ValueError as exc:
            raise TelegramWebAppAuthError("Malformed initData") from exc
        data: dict[str, str] = {}
        for key, value in pairs:
            if key in data:
                raise TelegramWebAppAuthError("Duplicate initData field")
            data[key] = value

        received_hash = data.pop("hash", None)
        if not received_hash:
            raise TelegramWebAppAuthError("Missing initData hash")
        if "auth_date" not in data:
            raise TelegramWebAppAuthError("Missing initData auth_date")
        if "user" not in data:
            raise TelegramWebAppAuthError("Missing initData user")

        data_check_string = "\n".join(f"{key}={data[key]}" for key in sorted(data))
        secret_key = hmac.new(
            b"WebAppData",
            self.bot_token.encode(),
            hashlib.sha256,
        ).digest()
        expected_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected_hash, received_hash):
            raise TelegramWebAppAuthError("Invalid initData hash")

        auth_date = _parse_auth_date(data["auth_date"])
        self._validate_auth_date(auth_date)
        user_payload = _parse_user(data["user"])
        telegram_id = user_payload.get("id")
        if not isinstance(telegram_id, int):
            raise TelegramWebAppAuthError("Invalid initData user id")
        return TelegramWebAppIdentity(telegram_id=telegram_id)

    def _validate_auth_date(self, auth_date: datetime) -> None:
        now = self.clock.now()
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        now = now.astimezone(UTC)
        age_seconds = (now - auth_date).total_seconds()
        if age_seconds > self.max_age_seconds:
            raise TelegramWebAppAuthError("Expired initData")
        if age_seconds < -WEBAPP_AUTH_FUTURE_SKEW_SECONDS:
            raise TelegramWebAppAuthError("Future initData auth_date")


def authorization_to_init_data(authorization: str | None) -> str:
    if not authorization:
        raise TelegramWebAppAuthError("Missing Authorization header")
    scheme, separator, value = authorization.partition(" ")
    if separator != " " or scheme.lower() != WEBAPP_AUTH_SCHEME or not value:
        raise TelegramWebAppAuthError("Invalid Authorization scheme")
    return value


def _parse_auth_date(value: str) -> datetime:
    try:
        timestamp = int(value)
    except ValueError as exc:
        raise TelegramWebAppAuthError("Malformed initData auth_date") from exc
    return datetime.fromtimestamp(timestamp, tz=UTC)


def _parse_user(value: str) -> dict[str, object]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise TelegramWebAppAuthError("Malformed initData user") from exc
    if not isinstance(payload, dict):
        raise TelegramWebAppAuthError("Malformed initData user")
    return payload
