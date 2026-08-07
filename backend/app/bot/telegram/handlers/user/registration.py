from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.telegram.handlers.user.shared import (
    clean_text as _clean_text,
)
from app.bot.telegram.handlers.user.shared import (
    delete_message as _delete_message,
)
from app.bot.telegram.handlers.user.shared import (
    delete_prompt_and_input as _delete_prompt_and_input,
)
from app.bot.telegram.handlers.user.shared import (
    is_valid_display_name as _is_valid_display_name,
)
from app.bot.telegram.handlers.user.shared import (
    send_input_prompt as _send_input_prompt,
)
from app.bot.telegram.handlers.user.shared import (
    send_registration_intro as _send_registration_intro,
)
from app.bot.telegram.keyboards.user import registration as user_registration_kb
from app.bot.telegram.notifications import notify_admins_about_registration
from app.bot.telegram.states import RegistrationStates
from app.bot.telegram.texts.user import registration as text
from app.services.registration_service import (
    RegistrationCandidateNotFoundError,
    registration_service,
)
from app.services.user_common import (
    IdentityAlreadyExistsError,
    InvalidDisplayNameError,
    RegistrationNotAllowedError,
)

router = Router(name="user.registration")


@router.callback_query(F.data == user_registration_kb.REGISTRATION_NEW_PLAYER_CALLBACK)
async def choose_new_player_registration(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is None:
        return

    await _delete_message(callback.message)
    await state.set_state(RegistrationStates.entering_new_display_name)
    await _send_input_prompt(callback.message, state, text.REGISTRATION_NEW_PLAYER_PROMPT)


@router.callback_query(F.data == user_registration_kb.REGISTRATION_LINK_EXISTING_CALLBACK)
async def choose_link_existing_registration(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is None:
        return

    await _delete_message(callback.message)
    await state.set_state(RegistrationStates.entering_link_name)
    await _send_input_prompt(callback.message, state, text.REGISTRATION_LINK_NAME_PROMPT)


@router.callback_query(F.data == user_registration_kb.REGISTRATION_RETRY_LINK_CALLBACK)
async def retry_link_existing_registration(callback: CallbackQuery, state: FSMContext) -> None:
    await choose_link_existing_registration(callback, state)


@router.callback_query(F.data == user_registration_kb.REGISTRATION_BACK_CALLBACK)
async def back_to_registration_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is None:
        return

    await _delete_message(callback.message)
    await state.clear()
    await _send_registration_intro(callback.message, state)


@router.message(RegistrationStates.entering_new_display_name)
async def enter_new_display_name(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return

    display_name = _clean_text(message.text or "")
    if not _is_valid_display_name(display_name):
        await message.answer(text.INVALID_DISPLAY_NAME)
        return

    try:
        request = await registration_service.submit_new_player_registration(
            message.from_user.id,
            display_name,
        )
    except IdentityAlreadyExistsError:
        await _delete_prompt_and_input(message, state)
        await state.clear()
        await message.answer(
            text.DISPLAY_NAME_ALREADY_EXISTS,
            reply_markup=user_registration_kb.registration_start_keyboard(),
        )
        return
    except (InvalidDisplayNameError, RegistrationNotAllowedError):
        await message.answer(text.REGISTRATION_NOT_ALLOWED)
        return

    await _delete_prompt_and_input(message, state)
    await state.clear()
    await notify_admins_about_registration(message.bot, request.id)
    await message.answer(text.REGISTRATION_SUBMITTED)


@router.message(RegistrationStates.entering_link_name)
async def enter_link_name(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return

    requested_link_name = _clean_text(message.text or "")
    if not _is_valid_display_name(requested_link_name):
        await message.answer(text.INVALID_DISPLAY_NAME)
        return

    try:
        request = await registration_service.submit_link_existing_registration(
            message.from_user.id,
            requested_link_name,
        )
    except RegistrationCandidateNotFoundError:
        await _delete_prompt_and_input(message, state)
        await state.clear()
        await message.answer(
            text.REGISTRATION_LINK_NOT_FOUND,
            reply_markup=user_registration_kb.registration_link_not_found_keyboard(),
        )
        return
    except (InvalidDisplayNameError, RegistrationNotAllowedError):
        await message.answer(text.REGISTRATION_NOT_ALLOWED)
        return

    await _delete_prompt_and_input(message, state)
    await state.clear()
    await notify_admins_about_registration(message.bot, request.id)
    await message.answer(text.REGISTRATION_SUBMITTED)
