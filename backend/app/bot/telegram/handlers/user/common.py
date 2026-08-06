# ruff: noqa: F401
import re

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from app.bot.telegram import keyboards, texts
from app.bot.telegram.formatters import (
    format_hall_of_fame,
    format_historical_tournament_result,
    format_history_months,
    format_history_tournaments,
    format_history_years,
    format_profile,
    format_rating,
    format_tournament_label,
    format_tournament_schedule,
)
from app.bot.telegram.notifications import notify_admins_about_registration
from app.bot.telegram.states import RegistrationStates
from app.services.dto import UserStartStatusView
from app.services.pagination import pagination_service
from app.services.profile_service import ProfileNotAllowedError, profile_service
from app.services.rating_service import RatingNotAllowedError, rating_service
from app.services.tournament_service import (
    TournamentCancellationUnavailableError,
    TournamentRegistrationNotAllowedError,
    TournamentScheduleNotAllowedError,
    TournamentUnavailableError,
    tournament_service,
)
from app.services.user_service import (
    ActiveUserRequiredError,
    IdentityAlreadyExistsError,
    InvalidDisplayNameError,
    RegistrationCandidateNotFoundError,
    RegistrationNotAllowedError,
    user_service,
)
from app.services.user_statistics_service import (
    HallOfFameNotAllowedError,
    HistoricalTournamentNotFoundError,
    HistoryNotAllowedError,
    user_statistics_service,
)


def _clean_text(value: str) -> str:
    return " ".join(value.split())


def _is_valid_display_name(value: str) -> bool:
    return 1 <= len(value) <= 255 and re.fullmatch(r"[\w\s.@-]+", value) is not None


async def _send_registration_intro(message: Message, state: FSMContext) -> None:
    await message.answer(
        texts.user.REGISTRATION_GREETING,
        reply_markup=keyboards.registration_start_keyboard(),
    )
    await state.set_state(None)


async def _delete_message(message: Message) -> None:
    try:
        await message.delete()
    except TelegramBadRequest:
        pass


async def _edit_history_message(
    callback: CallbackQuery,
    text: str,
    reply_markup: object,
    parse_mode: str | None = None,
) -> None:
    await callback.answer()
    if callback.message is None:
        return
    try:
        await callback.message.edit_text(
            text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
    except TelegramBadRequest:
        pass


async def _delete_prompt_and_input(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    prompt_message_id = data.get("prompt_message_id")
    if prompt_message_id:
        try:
            await message.bot.delete_message(
                chat_id=message.chat.id,
                message_id=prompt_message_id,
            )
        except TelegramBadRequest:
            pass

    await _delete_message(message)
    await state.update_data(prompt_message_id=None)


async def _send_input_prompt(
    message: Message,
    state: FSMContext,
    text: str,
) -> None:
    prompt = await message.answer(text)
    await state.update_data(prompt_message_id=prompt.message_id)


__all__ = [name for name in globals() if not name.startswith("__")]
