import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.telegram.handlers.admin.shared import (
    delete_callback_message as _delete_callback_message,
)
from app.bot.telegram.handlers.user.shared import clean_text as _clean_text
from app.bot.telegram.keyboards import labels
from app.bot.telegram.keyboards.superadmin import administrators as superadmin_administrators_kb
from app.bot.telegram.keyboards.superadmin import panel as superadmin_panel_kb
from app.bot.telegram.keyboards.user import menu as user_menu_kb
from app.bot.telegram.states import AdminAddStates
from app.bot.telegram.texts.admin import calendar as calendar_text
from app.bot.telegram.texts.superadmin import administrators as administrator_text
from app.bot.telegram.texts.superadmin import panel as panel_text
from app.services.access_policy import AdminAccessDeniedError
from app.services.admin_management_service import admin_management_service
from app.services.user_common import (
    UserNotFoundError,
    UserRoleAlreadyAssignedError,
)

logger = logging.getLogger(__name__)


router = Router(name="admin.administrators")


@router.message(F.text == labels.ADMIN_PANEL_ADD_ADMIN)
async def prompt_admin_candidate_search(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return

    try:
        await admin_management_service.require_add_admin_access(message.from_user.id)
    except AdminAccessDeniedError:
        await message.answer(panel_text.INSUFFICIENT_RIGHTS)
        return

    await state.set_state(AdminAddStates.entering_candidate_name)
    await message.answer(administrator_text.ADMIN_ADD_SEARCH_PROMPT)


@router.message(AdminAddStates.entering_candidate_name)
async def search_admin_candidate(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return

    query = _clean_text(message.text or "")
    try:
        candidates = await admin_management_service.search_admin_candidates_for_superadmin(
            message.from_user.id,
            query,
        )
    except AdminAccessDeniedError:
        await state.clear()
        await message.answer(panel_text.INSUFFICIENT_RIGHTS)
        return

    await state.update_data(admin_candidate_query=query)
    if not candidates:
        await message.answer(
            administrator_text.ADMIN_ADD_NOT_FOUND,
            reply_markup=superadmin_administrators_kb.admin_candidate_not_found_keyboard(),
        )
        return

    if len(candidates) == 1:
        await message.answer(
            administrator_text.add_confirmation(candidates[0].display_name),
            reply_markup=superadmin_administrators_kb.admin_add_confirmation_keyboard(
                candidates[0].id
            ),
        )
        return

    await message.answer(
        administrator_text.candidate_search_results(),
        reply_markup=superadmin_administrators_kb.admin_candidate_search_results_keyboard(
            candidates
        ),
    )


@router.callback_query(superadmin_administrators_kb.AdminCandidateCallback.filter())
async def select_admin_candidate(
    callback: CallbackQuery,
    callback_data: superadmin_administrators_kb.AdminCandidateCallback,
    state: FSMContext,
) -> None:
    try:
        if callback_data.action == superadmin_administrators_kb.AdminCandidateAction.CANCEL:
            await callback.answer(calendar_text.ADMIN_CALENDAR_CANCELLED)
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer(administrator_text.ADMIN_ADD_CANCELLED)
            await state.clear()
            return

        if callback_data.action == superadmin_administrators_kb.AdminCandidateAction.SEARCH_AGAIN:
            await callback.answer()
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer(administrator_text.ADMIN_ADD_SEARCH_PROMPT)
            await state.set_state(AdminAddStates.entering_candidate_name)
            return

        data = await state.get_data()
        query = data.get("admin_candidate_query", "")
        players = await admin_management_service.search_admin_candidates_for_superadmin(
            callback.from_user.id,
            str(query),
        )
    except AdminAccessDeniedError:
        await callback.answer(panel_text.INSUFFICIENT_RIGHTS, show_alert=True)
        return

    player = next(
        (candidate for candidate in players if candidate.id == callback_data.player_id),
        None,
    )
    if player is None:
        await callback.answer(administrator_text.PLAYER_NOT_FOUND, show_alert=True)
        return

    await callback.answer()
    if callback.message is not None:
        await _delete_callback_message(callback)
        await callback.message.answer(
            administrator_text.add_confirmation(player.display_name),
            reply_markup=superadmin_administrators_kb.admin_add_confirmation_keyboard(player.id),
        )


@router.callback_query(superadmin_administrators_kb.AdminAddCallback.filter())
async def confirm_add_admin(
    callback: CallbackQuery,
    callback_data: superadmin_administrators_kb.AdminAddCallback,
    state: FSMContext,
) -> None:
    if callback_data.action == superadmin_administrators_kb.AdminAddAction.CANCEL:
        await callback.answer(calendar_text.ADMIN_CALENDAR_CANCELLED)
        if callback.message is not None:
            await _delete_callback_message(callback)
            await callback.message.answer(administrator_text.ADMIN_ADD_CANCELLED)
        await state.clear()
        return

    if callback_data.action == superadmin_administrators_kb.AdminAddAction.BACK:
        data = await state.get_data()
        query = data.get("admin_candidate_query", "")
        try:
            candidates = await admin_management_service.search_admin_candidates_for_superadmin(
                callback.from_user.id,
                str(query),
            )
        except AdminAccessDeniedError:
            await callback.answer(panel_text.INSUFFICIENT_RIGHTS, show_alert=True)
            return

        await callback.answer()
        if callback.message is not None:
            await _delete_callback_message(callback)
            if candidates:
                await callback.message.answer(
                    administrator_text.candidate_search_results(),
                    reply_markup=superadmin_administrators_kb.admin_candidate_search_results_keyboard(
                        candidates
                    ),
                )
            else:
                await callback.message.answer(
                    administrator_text.ADMIN_ADD_SEARCH_PROMPT,
                )
                await state.set_state(AdminAddStates.entering_candidate_name)
        return

    try:
        player = await admin_management_service.add_admin(
            superadmin_telegram_id=callback.from_user.id,
            user_id=callback_data.player_id,
        )
    except AdminAccessDeniedError:
        await callback.answer(panel_text.INSUFFICIENT_RIGHTS, show_alert=True)
        return
    except UserNotFoundError:
        await callback.answer(administrator_text.PLAYER_NOT_FOUND, show_alert=True)
        return
    except UserRoleAlreadyAssignedError:
        await callback.answer(administrator_text.ADMIN_ALREADY_ASSIGNED, show_alert=True)
        return

    result_text = administrator_text.admin_added(player.display_name)
    await callback.answer(result_text)
    if callback.message is not None:
        await _delete_callback_message(callback)
        await callback.message.answer(
            result_text,
            reply_markup=superadmin_panel_kb.superadmin_panel_keyboard(),
        )
    await state.clear()

    try:
        await callback.bot.send_message(
            chat_id=player.telegram_id,
            text=administrator_text.ADMIN_ADDED_FOR_PLAYER,
            reply_markup=user_menu_kb.main_keyboard_after_role_update(player),
        )
    except (TelegramBadRequest, TelegramForbiddenError):
        pass
