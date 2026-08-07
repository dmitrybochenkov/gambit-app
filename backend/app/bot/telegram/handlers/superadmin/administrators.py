import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import CallbackQuery, Message

from app.bot.telegram.handlers.admin.shared import (
    delete_callback_message as _delete_callback_message,
)
from app.bot.telegram.keyboards import labels
from app.bot.telegram.keyboards.superadmin import administrators as superadmin_administrators_kb
from app.bot.telegram.keyboards.user import menu as user_menu_kb
from app.bot.telegram.texts.admin import calendar as calendar_text
from app.bot.telegram.texts.superadmin import administrators as administrator_text
from app.bot.telegram.texts.superadmin import panel as panel_text
from app.services.access_policy import AdminAccessDeniedError
from app.services.pagination import pagination_service
from app.services.user_service import (
    UserNotFoundError,
    UserRoleAlreadyAssignedError,
    user_service,
)

logger = logging.getLogger(__name__)


router = Router(name="admin.administrators")


@router.message(F.text == labels.ADMIN_PANEL_ADD_ADMIN)
async def show_admin_candidates(message: Message) -> None:
    if message.from_user is None:
        return

    try:
        players = await user_service.list_admin_candidates_for_superadmin(message.from_user.id)
    except AdminAccessDeniedError:
        await message.answer(panel_text.INSUFFICIENT_RIGHTS)
        return

    if not players:
        await message.answer(administrator_text.ADMIN_ADD_NO_CANDIDATES)
        return

    page = pagination_service.paginate(
        players,
        page=0,
        page_size=superadmin_administrators_kb.ADMIN_CANDIDATE_PAGE_SIZE,
    )
    await message.answer(
        administrator_text.candidate_list(page),
        reply_markup=superadmin_administrators_kb.admin_candidate_list_keyboard(page),
    )


@router.callback_query(superadmin_administrators_kb.AdminCandidateCallback.filter())
async def select_admin_candidate(
    callback: CallbackQuery,
    callback_data: superadmin_administrators_kb.AdminCandidateCallback,
) -> None:
    try:
        if callback_data.action == superadmin_administrators_kb.AdminCandidateAction.CANCEL:
            await callback.answer(calendar_text.ADMIN_CALENDAR_CANCELLED)
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer(calendar_text.ADMIN_CALENDAR_CANCELLED)
            return

        players = await user_service.list_admin_candidates_for_superadmin(callback.from_user.id)
    except AdminAccessDeniedError:
        await callback.answer(panel_text.INSUFFICIENT_RIGHTS, show_alert=True)
        return

    if callback_data.action == superadmin_administrators_kb.AdminCandidateAction.PAGE:
        page = pagination_service.paginate(
            players,
            page=callback_data.page,
            page_size=superadmin_administrators_kb.ADMIN_CANDIDATE_PAGE_SIZE,
        )
        await callback.answer()
        if callback.message is not None:
            await callback.message.edit_text(
                administrator_text.candidate_list(page),
                reply_markup=superadmin_administrators_kb.admin_candidate_list_keyboard(page),
            )
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
) -> None:
    if callback_data.action == superadmin_administrators_kb.AdminAddAction.CANCEL:
        await callback.answer(calendar_text.ADMIN_CALENDAR_CANCELLED)
        if callback.message is not None:
            await _delete_callback_message(callback)
            await callback.message.answer(calendar_text.ADMIN_CALENDAR_CANCELLED)
        return

    try:
        player = await user_service.add_admin(
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

    await callback.answer(administrator_text.ADMIN_ADDED)
    if callback.message is not None:
        await _delete_callback_message(callback)
        await callback.message.answer(administrator_text.ADMIN_ADDED)

    try:
        await callback.bot.send_message(
            chat_id=player.telegram_id,
            text=administrator_text.ADMIN_ADDED_FOR_PLAYER,
            reply_markup=user_menu_kb.main_keyboard_after_role_update(player),
        )
    except (TelegramBadRequest, TelegramForbiddenError):
        pass
