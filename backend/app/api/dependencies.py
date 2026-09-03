from dataclasses import dataclass

from fastapi import Header

from app.api import errors
from app.api.auth import (
    TelegramWebAppAuthError,
    TelegramWebAppInitDataVerifier,
    authorization_to_init_data,
)
from app.config import settings
from app.services.user_access_service import user_access_service


@dataclass(frozen=True)
class AuthenticatedActor:
    user_id: int
    telegram_id: int
    role: str
    display_name: str
    gender: str | None


async def current_actor(
    authorization: str | None = Header(default=None),
) -> AuthenticatedActor:
    try:
        raw_init_data = authorization_to_init_data(authorization)
        identity = TelegramWebAppInitDataVerifier(
            bot_token=settings.telegram_bot_token,
            max_age_seconds=settings.telegram_webapp_auth_max_age_seconds,
        ).verify(raw_init_data)
    except TelegramWebAppAuthError as exc:
        raise errors.unauthorized("Invalid Telegram WebApp initData") from exc

    user = await user_access_service.get_by_telegram_id(identity.telegram_id)
    if user is None:
        raise errors.not_found("User is not registered")
    if not user.is_active:
        raise errors.forbidden("User is not active")
    if user.telegram_id is None:
        raise errors.forbidden("User is not linked to Telegram")
    return AuthenticatedActor(
        user_id=user.id,
        telegram_id=user.telegram_id,
        role=user.role.value,
        display_name=user.display_name,
        gender=user.gender.value if user.gender is not None else None,
    )
