# ruff: noqa: F403,F405
from aiogram import Router

from app.bot.telegram.handlers.admin.common import *  # noqa: F403

router = Router(name="admin.registrations")


@router.message(F.text == keyboards.ADMIN_PANEL_REGISTRATIONS)
async def show_pending_registrations(message: Message) -> None:
    if message.from_user is None:
        return

    try:
        await user_service.require_superadmin(message.from_user.id)
        admin_panel = await user_service.get_admin_panel_for_admin(message.from_user.id)
    except AdminAccessDeniedError:
        await message.answer(texts.admin.ACCESS_DENIED)
        return

    reviews = admin_panel.reviews
    if not reviews:
        await message.answer(texts.admin.NO_PENDING_REGISTRATIONS)
        return

    page = pagination_service.paginate(
        reviews,
        page=0,
        page_size=keyboards.REGISTRATION_LIST_PAGE_SIZE,
    )
    await message.answer(
        texts.admin.registration_list(page),
        reply_markup=keyboards.registration_list_keyboard(page),
    )


@router.callback_query(keyboards.RegistrationListCallback.filter())
async def review_registration_list(
    callback: CallbackQuery,
    callback_data: keyboards.RegistrationListCallback,
) -> None:
    try:
        if callback_data.action == keyboards.RegistrationListAction.CANCEL:
            await callback.answer(texts.admin.REGISTRATION_CANCELLED)
            if callback.message is not None:
                try:
                    await callback.message.delete()
                except TelegramBadRequest:
                    pass
            return

        if callback_data.action == keyboards.RegistrationListAction.OPEN:
            review = await user_service.get_registration_review_for_admin(
                admin_telegram_id=callback.from_user.id,
                request_id=callback_data.request_id,
            )
            await callback.answer()
            if callback.message is not None:
                await callback.message.edit_text(
                    format_registration_review(review),
                    reply_markup=keyboards.registration_review_keyboard(
                        review.request.id,
                        can_edit_name=review.request.request_type == "new_player",
                        can_select_candidate=review.request.request_type == "link_existing_player",
                    ),
                )
            return

        await user_service.require_superadmin(callback.from_user.id)
        admin_panel = await user_service.get_admin_panel_for_admin(callback.from_user.id)
        reviews = admin_panel.reviews
        if not reviews:
            await callback.answer()
            if callback.message is not None:
                await callback.message.edit_text(
                    texts.admin.NO_PENDING_REGISTRATIONS,
                    reply_markup=None,
                )
            return

        page = pagination_service.paginate(
            reviews,
            page=callback_data.page,
            page_size=keyboards.REGISTRATION_LIST_PAGE_SIZE,
        )
        await callback.answer()
        if callback.message is not None:
            await callback.message.edit_text(
                texts.admin.registration_list(page),
                reply_markup=keyboards.registration_list_keyboard(page),
            )
    except AdminAccessDeniedError:
        await callback.answer(texts.admin.ACCESS_DENIED, show_alert=True)
        return
    except (UserNotFoundError, RegistrationAlreadyReviewedError):
        await callback.answer(
            texts.admin.REGISTRATION_ALREADY_REVIEWED,
            show_alert=True,
        )


@router.callback_query(keyboards.RegistrationReviewCallback.filter())
async def review_registration(
    callback: CallbackQuery,
    callback_data: keyboards.RegistrationReviewCallback,
) -> None:
    try:
        if callback_data.action == keyboards.RegistrationReviewAction.SELECT_CANDIDATE:
            review = await user_service.get_registration_review_for_admin(
                admin_telegram_id=callback.from_user.id,
                request_id=callback_data.request_id,
            )
            await callback.answer()
            if callback.message is not None:
                await callback.message.edit_reply_markup(
                    reply_markup=keyboards.registration_candidate_selection_keyboard(
                        callback_data.request_id,
                        review.candidates,
                    )
                )
            return

        if callback_data.action == keyboards.RegistrationReviewAction.EDIT_NAME:
            await callback.answer("Редактирование имени добавим следующим шагом.", show_alert=True)
            return

        if callback_data.action == keyboards.RegistrationReviewAction.APPROVE:
            review_result = await user_service.approve_registration(
                superadmin_telegram_id=callback.from_user.id,
                request_id=callback_data.request_id,
            )
            result_text = texts.admin.REGISTRATION_APPROVED
            player_text = "Ваша заявка одобрена."
            player_keyboard = keyboards.main_keyboard_after_registration()
        elif callback_data.action == keyboards.RegistrationReviewAction.CANCEL:
            await callback.answer(texts.admin.REGISTRATION_CANCELLED)
            if callback.message is not None:
                try:
                    await callback.message.delete()
                except TelegramBadRequest:
                    pass
            return
        else:
            review_result = await user_service.reject_registration(
                superadmin_telegram_id=callback.from_user.id,
                request_id=callback_data.request_id,
            )
            result_text = texts.admin.REGISTRATION_REJECTED
            player_text = "Ваша заявка отклонена."
            player_keyboard = ReplyKeyboardRemove()
    except AdminAccessDeniedError:
        await callback.answer(texts.admin.ACCESS_DENIED, show_alert=True)
        return
    except UserNotFoundError:
        await callback.answer(texts.admin.PLAYER_NOT_FOUND, show_alert=True)
        return
    except RegistrationAlreadyReviewedError:
        await callback.answer(
            texts.admin.REGISTRATION_ALREADY_REVIEWED,
            show_alert=True,
        )
        return

    await _send_registration_review_result(
        callback=callback,
        review_result=review_result,
        result_text=result_text,
        player_text=player_text,
        player_keyboard=player_keyboard,
    )


@router.callback_query(keyboards.RegistrationCandidateSelectionCallback.filter())
async def select_registration_candidate(
    callback: CallbackQuery,
    callback_data: keyboards.RegistrationCandidateSelectionCallback,
) -> None:
    try:
        review = await user_service.select_registration_candidate(
            superadmin_telegram_id=callback.from_user.id,
            request_id=callback_data.request_id,
            user_id=callback_data.user_id,
        )
    except AdminAccessDeniedError:
        await callback.answer(texts.admin.ACCESS_DENIED, show_alert=True)
        return
    except UserNotFoundError:
        await callback.answer(texts.admin.PLAYER_NOT_FOUND, show_alert=True)
        return
    except (RegistrationAlreadyReviewedError, RegistrationCandidateNotFoundError):
        await callback.answer(
            texts.admin.REGISTRATION_ALREADY_REVIEWED,
            show_alert=True,
        )
        return

    await callback.answer("Игрок выбран.")
    if callback.message is not None:
        await callback.message.edit_text(
            format_registration_review(review),
            reply_markup=keyboards.registration_review_keyboard(
                review.request.id,
                can_select_candidate=True,
            ),
        )


async def _send_registration_review_result(
    callback: CallbackQuery,
    review_result: RegistrationReviewResultView,
    result_text: str,
    player_text: str,
    player_keyboard: object,
) -> None:
    await callback.answer(result_text)
    admin_review_text = callback.message.text if callback.message is not None else ""
    reviewed_text = texts.admin.reviewed_by_admin(
        review_text=admin_review_text,
        result_text=result_text,
        admin_name=callback.from_user.full_name,
    )
    if callback.message is not None:
        try:
            await callback.message.edit_text(reviewed_text)
        except TelegramBadRequest:
            pass

    for admin in review_result.admins:
        if admin.telegram_id is None or admin.telegram_id == callback.from_user.id:
            continue
        try:
            await callback.bot.send_message(
                chat_id=admin.telegram_id,
                text=reviewed_text,
            )
        except (TelegramBadRequest, TelegramForbiddenError):
            continue

    try:
        await callback.bot.send_message(
            chat_id=review_result.request.telegram_id,
            text=player_text,
            reply_markup=player_keyboard,
        )
    except (TelegramBadRequest, TelegramForbiddenError):
        pass
