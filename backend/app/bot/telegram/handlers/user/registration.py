# ruff: noqa: F403,F405
from aiogram import Router

from app.bot.telegram.handlers.user.common import *  # noqa: F403

router = Router(name="user.registration")


@router.callback_query(F.data == keyboards.REGISTRATION_NEW_PLAYER_CALLBACK)
async def choose_new_player_registration(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is None:
        return

    await _delete_message(callback.message)
    await state.set_state(RegistrationStates.entering_new_display_name)
    await _send_input_prompt(callback.message, state, texts.user.REGISTRATION_NEW_PLAYER_PROMPT)


@router.callback_query(F.data == keyboards.REGISTRATION_LINK_EXISTING_CALLBACK)
async def choose_link_existing_registration(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is None:
        return

    await _delete_message(callback.message)
    await state.set_state(RegistrationStates.entering_link_name)
    await _send_input_prompt(callback.message, state, texts.user.REGISTRATION_LINK_NAME_PROMPT)


@router.callback_query(F.data == keyboards.REGISTRATION_RETRY_LINK_CALLBACK)
async def retry_link_existing_registration(callback: CallbackQuery, state: FSMContext) -> None:
    await choose_link_existing_registration(callback, state)


@router.callback_query(F.data == keyboards.REGISTRATION_BACK_CALLBACK)
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
        await message.answer(texts.user.INVALID_DISPLAY_NAME)
        return

    try:
        request = await user_service.submit_new_player_registration(
            message.from_user.id,
            display_name,
        )
    except IdentityAlreadyExistsError:
        await _delete_prompt_and_input(message, state)
        await state.clear()
        await message.answer(
            texts.user.DISPLAY_NAME_ALREADY_EXISTS,
            reply_markup=keyboards.registration_start_keyboard(),
        )
        return
    except (InvalidDisplayNameError, RegistrationNotAllowedError):
        await message.answer(texts.user.REGISTRATION_NOT_ALLOWED)
        return

    await _delete_prompt_and_input(message, state)
    await state.clear()
    await notify_admins_about_registration(message.bot, request.id)
    await message.answer(texts.user.REGISTRATION_SUBMITTED)


@router.message(RegistrationStates.entering_link_name)
async def enter_link_name(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return

    requested_link_name = _clean_text(message.text or "")
    if not _is_valid_display_name(requested_link_name):
        await message.answer(texts.user.INVALID_DISPLAY_NAME)
        return

    try:
        request = await user_service.submit_link_existing_registration(
            message.from_user.id,
            requested_link_name,
        )
    except RegistrationCandidateNotFoundError:
        await _delete_prompt_and_input(message, state)
        await state.clear()
        await message.answer(
            texts.user.REGISTRATION_LINK_NOT_FOUND,
            reply_markup=keyboards.registration_link_not_found_keyboard(),
        )
        return
    except (InvalidDisplayNameError, RegistrationNotAllowedError):
        await message.answer(texts.user.REGISTRATION_NOT_ALLOWED)
        return

    await _delete_prompt_and_input(message, state)
    await state.clear()
    await notify_admins_about_registration(message.bot, request.id)
    await message.answer(texts.user.REGISTRATION_SUBMITTED)
