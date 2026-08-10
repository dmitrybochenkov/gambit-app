import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.telegram.handlers.admin.shared import (
    delete_callback_message as _delete_callback_message,
)
from app.bot.telegram.handlers.user.shared import clean_text as _clean_text
from app.bot.telegram.keyboards import labels
from app.bot.telegram.keyboards.superadmin import panel as superadmin_panel_kb
from app.bot.telegram.keyboards.superadmin import users as superadmin_users_kb
from app.bot.telegram.message_edit import edit_message_reply_markup_by_id_if_changed
from app.bot.telegram.states import UserRenameStates
from app.bot.telegram.texts.admin import calendar as calendar_text
from app.bot.telegram.texts.superadmin import panel as panel_text
from app.bot.telegram.texts.superadmin import users as text
from app.services.access_policy import ActiveUserRequiredError, AdminAccessDeniedError
from app.services.player_search import InvalidDisplayNameError
from app.services.user_common import UserNotFoundError
from app.services.user_rename_service import (
    UserRenameNameOccupiedError,
    UserRenameSameNameError,
    user_rename_service,
)

logger = logging.getLogger(__name__)

router = Router(name="superadmin.users")


@router.message(F.text == labels.ADMIN_PANEL_RENAME_USER)
async def prompt_user_rename_search(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return

    try:
        await user_rename_service.require_rename_access(message.from_user.id)
    except (ActiveUserRequiredError, AdminAccessDeniedError):
        await message.answer(panel_text.INSUFFICIENT_RIGHTS)
        return

    await state.set_state(UserRenameStates.entering_current_name)
    prompt = await message.answer(
        text.USER_RENAME_PROMPT,
        reply_markup=superadmin_users_kb.user_rename_prompt_keyboard(),
    )
    await state.update_data(user_rename_prompt_message_id=prompt.message_id)


@router.message(UserRenameStates.entering_current_name)
async def search_user_to_rename(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return

    query = _clean_text(message.text or "")
    data = await state.get_data()
    await _clear_user_rename_prompt_markup(message, data)
    try:
        candidates = await user_rename_service.search_users_for_rename(
            message.from_user.id,
            query,
        )
    except (ActiveUserRequiredError, AdminAccessDeniedError):
        await state.clear()
        await message.answer(panel_text.INSUFFICIENT_RIGHTS)
        return

    await state.update_data(user_rename_query=query)
    if not candidates:
        await message.answer(
            text.USER_RENAME_NOT_FOUND,
            reply_markup=superadmin_users_kb.user_rename_prompt_keyboard(),
        )
        return

    if len(candidates) == 1:
        await _show_new_name_prompt(message, state, message.from_user.id, candidates[0].id)
        return

    await message.answer(
        text.USER_RENAME_RESULTS_TITLE,
        reply_markup=superadmin_users_kb.user_rename_search_results_keyboard(candidates),
    )


@router.callback_query(superadmin_users_kb.UserRenameSearchCallback.filter())
async def select_user_to_rename(
    callback: CallbackQuery,
    callback_data: superadmin_users_kb.UserRenameSearchCallback,
    state: FSMContext,
) -> None:
    if callback_data.action == superadmin_users_kb.UserRenameSearchAction.CANCEL:
        await _cancel_user_rename(callback, state)
        return

    if callback_data.action == superadmin_users_kb.UserRenameSearchAction.BACK:
        await callback.answer()
        if callback.message is not None:
            await _delete_callback_message(callback)
            prompt = await callback.message.answer(
                text.USER_RENAME_PROMPT,
                reply_markup=superadmin_users_kb.user_rename_prompt_keyboard(),
            )
            await state.update_data(user_rename_prompt_message_id=prompt.message_id)
        await state.set_state(UserRenameStates.entering_current_name)
        return

    await callback.answer()
    if callback.message is not None:
        await _delete_callback_message(callback)
        await _show_new_name_prompt(
            callback.message,
            state,
            callback.from_user.id,
            callback_data.user_id,
        )


@router.message(UserRenameStates.entering_new_display_name)
async def enter_new_user_display_name(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return

    data = await state.get_data()
    target_user_id = int(data.get("target_user_id") or 0)
    old_display_name = str(data.get("old_display_name") or "")
    if target_user_id <= 0 or not old_display_name:
        await state.clear()
        await message.answer(text.USER_RENAME_STALE)
        return

    new_display_name = _clean_text(message.text or "")
    try:
        await user_rename_service.validate_new_display_name(
            message.from_user.id,
            target_user_id,
            new_display_name,
        )
    except (ActiveUserRequiredError, AdminAccessDeniedError):
        await state.clear()
        await message.answer(panel_text.INSUFFICIENT_RIGHTS)
        return
    except UserNotFoundError:
        await state.clear()
        await message.answer(text.USER_RENAME_STALE)
        return
    except InvalidDisplayNameError:
        await message.answer(text.USER_RENAME_INVALID_NAME)
        return
    except UserRenameNameOccupiedError:
        await message.answer(text.USER_RENAME_OCCUPIED)
        return
    except UserRenameSameNameError:
        await message.answer(text.USER_RENAME_SAME_NAME)
        return

    await state.set_state(UserRenameStates.confirming_user_rename)
    await state.update_data(new_display_name=new_display_name)
    await message.answer(
        text.confirmation(old_display_name, new_display_name),
        reply_markup=superadmin_users_kb.user_rename_confirmation_keyboard(target_user_id),
    )


@router.callback_query(superadmin_users_kb.UserRenameConfirmCallback.filter())
async def confirm_user_rename(
    callback: CallbackQuery,
    callback_data: superadmin_users_kb.UserRenameConfirmCallback,
    state: FSMContext,
) -> None:
    if callback_data.action == superadmin_users_kb.UserRenameConfirmAction.CANCEL:
        await _cancel_user_rename(callback, state)
        return

    data = await state.get_data()
    target_user_id = int(data.get("target_user_id") or 0)
    old_display_name = str(data.get("old_display_name") or "")
    new_display_name = str(data.get("new_display_name") or "")
    if target_user_id != callback_data.user_id or not old_display_name or not new_display_name:
        await callback.answer(text.USER_RENAME_STALE, show_alert=True)
        return

    if callback_data.action == superadmin_users_kb.UserRenameConfirmAction.BACK:
        await callback.answer()
        await state.set_state(UserRenameStates.entering_new_display_name)
        if callback.message is not None:
            await _delete_callback_message(callback)
            await callback.message.answer(text.new_name_prompt(old_display_name))
        return

    try:
        renamed = await user_rename_service.rename_user(
            callback.from_user.id,
            target_user_id,
            new_display_name,
            old_display_name,
        )
    except (ActiveUserRequiredError, AdminAccessDeniedError):
        await callback.answer(panel_text.INSUFFICIENT_RIGHTS, show_alert=True)
        return
    except (UserNotFoundError, UserRenameNameOccupiedError, UserRenameSameNameError):
        await callback.answer(text.USER_RENAME_STALE, show_alert=True)
        return
    except InvalidDisplayNameError:
        await callback.answer(text.USER_RENAME_INVALID_NAME, show_alert=True)
        return

    await callback.answer(text.success(old_display_name, renamed.display_name))
    if callback.message is not None:
        await _delete_callback_message(callback)
        await callback.message.answer(
            text.success(old_display_name, renamed.display_name),
            reply_markup=superadmin_panel_kb.superadmin_panel_keyboard(),
        )
    await state.clear()


async def _show_new_name_prompt(
    message: Message,
    state: FSMContext,
    actor_telegram_id: int,
    user_id: int,
) -> None:
    try:
        target = await user_rename_service.get_target_for_rename(actor_telegram_id, user_id)
    except (ActiveUserRequiredError, AdminAccessDeniedError):
        await state.clear()
        await message.answer(panel_text.INSUFFICIENT_RIGHTS)
        return
    except UserNotFoundError:
        await message.answer(text.USER_RENAME_STALE)
        return

    await state.set_state(UserRenameStates.entering_new_display_name)
    await state.update_data(target_user_id=target.id, old_display_name=target.display_name)
    await message.answer(text.new_name_prompt(target.display_name))


async def _cancel_user_rename(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer(calendar_text.ADMIN_CALENDAR_CANCELLED)
    if callback.message is not None:
        await _delete_callback_message(callback)
        await callback.message.answer(
            text.USER_RENAME_CANCELLED,
            reply_markup=superadmin_panel_kb.superadmin_panel_keyboard(),
        )
    await state.clear()


async def _clear_user_rename_prompt_markup(
    message: Message,
    data: dict[str, object],
) -> None:
    prompt_message_id = int(data.get("user_rename_prompt_message_id") or 0)
    if prompt_message_id <= 0:
        return
    try:
        await edit_message_reply_markup_by_id_if_changed(
            message.bot,
            chat_id=message.chat.id,
            message_id=prompt_message_id,
            reply_markup=None,
        )
    except TelegramBadRequest:
        logger.info("Failed to clear user rename prompt markup", exc_info=True)
