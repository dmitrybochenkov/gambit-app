# ruff: noqa: F403,F405
from aiogram import Router

from app.bot.telegram.handlers.admin.common import *  # noqa: F403

router = Router(name="admin.administrators")


@router.message(F.text == keyboards.ADMIN_PANEL_ADD_ADMIN)
async def show_admin_candidates(message: Message) -> None:
    if message.from_user is None:
        return

    try:
        players = await user_service.list_admin_candidates_for_superadmin(message.from_user.id)
    except AdminAccessDeniedError:
        await message.answer(texts.admin.INSUFFICIENT_RIGHTS)
        return

    if not players:
        await message.answer(texts.admin.ADMIN_ADD_NO_CANDIDATES)
        return

    page = pagination_service.paginate(
        players,
        page=0,
        page_size=keyboards.ADMIN_CANDIDATE_PAGE_SIZE,
    )
    await message.answer(
        texts.admin.admin_candidate_list(page),
        reply_markup=keyboards.admin_candidate_list_keyboard(page),
    )


@router.callback_query(keyboards.AdminCandidateCallback.filter())
async def select_admin_candidate(
    callback: CallbackQuery,
    callback_data: keyboards.AdminCandidateCallback,
) -> None:
    try:
        if callback_data.action == keyboards.AdminCandidateAction.CANCEL:
            await callback.answer(texts.admin.ADMIN_CALENDAR_CANCELLED)
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer(texts.admin.ADMIN_CALENDAR_CANCELLED)
            return

        players = await user_service.list_admin_candidates_for_superadmin(callback.from_user.id)
    except AdminAccessDeniedError:
        await callback.answer(texts.admin.INSUFFICIENT_RIGHTS, show_alert=True)
        return

    if callback_data.action == keyboards.AdminCandidateAction.PAGE:
        page = pagination_service.paginate(
            players,
            page=callback_data.page,
            page_size=keyboards.ADMIN_CANDIDATE_PAGE_SIZE,
        )
        await callback.answer()
        if callback.message is not None:
            await callback.message.edit_text(
                texts.admin.admin_candidate_list(page),
                reply_markup=keyboards.admin_candidate_list_keyboard(page),
            )
        return

    player = next(
        (candidate for candidate in players if candidate.id == callback_data.player_id),
        None,
    )
    if player is None:
        await callback.answer(texts.admin.PLAYER_NOT_FOUND, show_alert=True)
        return

    await callback.answer()
    if callback.message is not None:
        await _delete_callback_message(callback)
        await callback.message.answer(
            texts.admin.admin_add_confirmation(player.display_name),
            reply_markup=keyboards.admin_add_confirmation_keyboard(player.id),
        )


@router.callback_query(keyboards.AdminAddCallback.filter())
async def confirm_add_admin(
    callback: CallbackQuery,
    callback_data: keyboards.AdminAddCallback,
) -> None:
    if callback_data.action == keyboards.AdminAddAction.CANCEL:
        await callback.answer(texts.admin.ADMIN_CALENDAR_CANCELLED)
        if callback.message is not None:
            await _delete_callback_message(callback)
            await callback.message.answer(texts.admin.ADMIN_CALENDAR_CANCELLED)
        return

    try:
        player = await user_service.add_admin(
            superadmin_telegram_id=callback.from_user.id,
            player_id=callback_data.player_id,
        )
    except AdminAccessDeniedError:
        await callback.answer(texts.admin.INSUFFICIENT_RIGHTS, show_alert=True)
        return
    except UserNotFoundError:
        await callback.answer(texts.admin.PLAYER_NOT_FOUND, show_alert=True)
        return
    except UserRoleAlreadyAssignedError:
        await callback.answer(texts.admin.ADMIN_ALREADY_ASSIGNED, show_alert=True)
        return

    await callback.answer(texts.admin.ADMIN_ADDED)
    if callback.message is not None:
        await _delete_callback_message(callback)
        await callback.message.answer(texts.admin.ADMIN_ADDED)

    try:
        await callback.bot.send_message(
            chat_id=player.telegram_id,
            text=texts.admin.ADMIN_ADDED_FOR_PLAYER,
            reply_markup=keyboards.main_keyboard_after_role_update(player),
        )
    except (TelegramBadRequest, TelegramForbiddenError):
        pass
