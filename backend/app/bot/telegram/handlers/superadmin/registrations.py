import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from app.bot.telegram.keyboards import labels
from app.bot.telegram.keyboards.superadmin import registrations as superadmin_registrations_kb
from app.bot.telegram.keyboards.user import menu as user_menu_kb
from app.bot.telegram.notifications import format_registration_review
from app.bot.telegram.texts.superadmin import panel as panel_text
from app.bot.telegram.texts.superadmin import registrations as text
from app.services.access_policy import AdminAccessDeniedError
from app.services.dto.registrations import RegistrationReviewResultView
from app.services.pagination import pagination_service
from app.services.registration_review_service import registration_review_service
from app.services.user_common import (
    IdentityAlreadyExistsError,
    RegistrationAlreadyReviewedError,
    RegistrationCandidateNotFoundError,
    RegistrationNotAllowedError,
    UserNotFoundError,
)

logger = logging.getLogger(__name__)


router = Router(name="admin.registrations")


@router.message(F.text == labels.ADMIN_PANEL_REGISTRATIONS)
async def show_pending_registrations(message: Message) -> None:
    if message.from_user is None:
        return

    try:
        reviews = await registration_review_service.list_pending_reviews_for_superadmin(
            message.from_user.id
        )
    except AdminAccessDeniedError:
        await message.answer(panel_text.INSUFFICIENT_RIGHTS)
        return

    if not reviews:
        await message.answer(text.NO_PENDING_REGISTRATIONS)
        return

    page = pagination_service.paginate(
        reviews,
        page=0,
        page_size=superadmin_registrations_kb.REGISTRATION_LIST_PAGE_SIZE,
    )
    await message.answer(
        text.registration_list(page),
        reply_markup=superadmin_registrations_kb.registration_list_keyboard(page),
    )


@router.callback_query(superadmin_registrations_kb.RegistrationListCallback.filter())
async def review_registration_list(
    callback: CallbackQuery,
    callback_data: superadmin_registrations_kb.RegistrationListCallback,
) -> None:
    try:
        if callback_data.action == superadmin_registrations_kb.RegistrationListAction.CANCEL:
            await callback.answer(text.REGISTRATION_CANCELLED)
            if callback.message is not None:
                try:
                    await callback.message.delete()
                except TelegramBadRequest:
                    pass
            return

        if callback_data.action == superadmin_registrations_kb.RegistrationListAction.OPEN:
            review = await registration_review_service.get_registration_review_for_admin(
                admin_telegram_id=callback.from_user.id,
                request_id=callback_data.request_id,
            )
            await callback.answer()
            if callback.message is not None:
                await callback.message.edit_text(
                    format_registration_review(review),
                    reply_markup=superadmin_registrations_kb.registration_review_keyboard_for_review(
                        review
                    ),
                )
            return

        reviews = await registration_review_service.list_pending_reviews_for_superadmin(
            callback.from_user.id
        )
        if not reviews:
            await callback.answer()
            if callback.message is not None:
                await callback.message.edit_text(
                    text.NO_PENDING_REGISTRATIONS,
                    reply_markup=None,
                )
            return

        page = pagination_service.paginate(
            reviews,
            page=callback_data.page,
            page_size=superadmin_registrations_kb.REGISTRATION_LIST_PAGE_SIZE,
        )
        await callback.answer()
        if callback.message is not None:
            await callback.message.edit_text(
                text.registration_list(page),
                reply_markup=superadmin_registrations_kb.registration_list_keyboard(page),
            )
    except AdminAccessDeniedError:
        await callback.answer(panel_text.INSUFFICIENT_RIGHTS, show_alert=True)
        return
    except (UserNotFoundError, RegistrationAlreadyReviewedError):
        await callback.answer(
            text.REGISTRATION_ALREADY_REVIEWED,
            show_alert=True,
        )


@router.callback_query(superadmin_registrations_kb.RegistrationReviewCallback.filter())
async def review_registration(
    callback: CallbackQuery,
    callback_data: superadmin_registrations_kb.RegistrationReviewCallback,
) -> None:
    try:
        if (
            callback_data.action
            == superadmin_registrations_kb.RegistrationReviewAction.SELECT_CANDIDATE
        ):
            review = await registration_review_service.get_registration_review_for_admin(
                admin_telegram_id=callback.from_user.id,
                request_id=callback_data.request_id,
            )
            await callback.answer()
            if callback.message is not None:
                await callback.message.edit_reply_markup(
                    reply_markup=superadmin_registrations_kb.registration_candidate_selection_keyboard(
                        callback_data.request_id,
                        review.candidates,
                    )
                )
            return

        if callback_data.action == superadmin_registrations_kb.RegistrationReviewAction.APPROVE:
            review_result = await registration_review_service.approve_registration(
                superadmin_telegram_id=callback.from_user.id,
                request_id=callback_data.request_id,
            )
            result_text = text.REGISTRATION_APPROVED
            player_text = "Ваша заявка одобрена."
            player_keyboard = user_menu_kb.main_keyboard_after_registration()
        elif callback_data.action == superadmin_registrations_kb.RegistrationReviewAction.CANCEL:
            await callback.answer(text.REGISTRATION_CANCELLED)
            if callback.message is not None:
                try:
                    await callback.message.delete()
                except TelegramBadRequest:
                    pass
            return
        else:
            review_result = await registration_review_service.reject_registration(
                superadmin_telegram_id=callback.from_user.id,
                request_id=callback_data.request_id,
            )
            result_text = text.REGISTRATION_REJECTED
            player_text = "Ваша заявка отклонена."
            player_keyboard = ReplyKeyboardRemove()
    except AdminAccessDeniedError:
        await callback.answer(panel_text.INSUFFICIENT_RIGHTS, show_alert=True)
        return
    except UserNotFoundError:
        await callback.answer(text.PLAYER_NOT_FOUND, show_alert=True)
        return
    except RegistrationAlreadyReviewedError:
        await callback.answer(
            text.REGISTRATION_ALREADY_REVIEWED,
            show_alert=True,
        )
        return
    except (
        IdentityAlreadyExistsError,
        RegistrationCandidateNotFoundError,
        RegistrationNotAllowedError,
    ):
        await callback.answer(text.REGISTRATION_NOT_ALLOWED, show_alert=True)
        return

    await _send_registration_review_result(
        callback=callback,
        review_result=review_result,
        result_text=result_text,
        player_text=player_text,
        player_keyboard=player_keyboard,
    )


@router.callback_query(superadmin_registrations_kb.RegistrationCandidateSelectionCallback.filter())
async def select_registration_candidate(
    callback: CallbackQuery,
    callback_data: superadmin_registrations_kb.RegistrationCandidateSelectionCallback,
) -> None:
    try:
        review = await registration_review_service.select_registration_candidate(
            superadmin_telegram_id=callback.from_user.id,
            request_id=callback_data.request_id,
            user_id=callback_data.user_id,
        )
    except AdminAccessDeniedError:
        await callback.answer(panel_text.INSUFFICIENT_RIGHTS, show_alert=True)
        return
    except UserNotFoundError:
        await callback.answer(text.PLAYER_NOT_FOUND, show_alert=True)
        return
    except (RegistrationAlreadyReviewedError, RegistrationCandidateNotFoundError):
        await callback.answer(
            text.REGISTRATION_ALREADY_REVIEWED,
            show_alert=True,
        )
        return
    except (IdentityAlreadyExistsError, RegistrationNotAllowedError):
        await callback.answer(text.REGISTRATION_NOT_ALLOWED, show_alert=True)
        return

    await callback.answer("Игрок выбран.")
    if callback.message is not None:
        await callback.message.edit_text(
            text.registration_candidate_confirmation(
                review.selected_candidate.user.display_name
                if review.selected_candidate is not None
                else ""
            ),
            reply_markup=superadmin_registrations_kb.registration_candidate_confirmation_keyboard(
                callback_data.request_id,
                callback_data.user_id,
            ),
        )


@router.callback_query(superadmin_registrations_kb.RegistrationCandidateConfirmCallback.filter())
async def confirm_registration_candidate(
    callback: CallbackQuery,
    callback_data: superadmin_registrations_kb.RegistrationCandidateConfirmCallback,
) -> None:
    try:
        if (
            callback_data.action
            == superadmin_registrations_kb.RegistrationCandidateConfirmAction.CANCEL
        ):
            await callback.answer(text.REGISTRATION_CANCELLED)
            if callback.message is not None:
                try:
                    await callback.message.delete()
                except TelegramBadRequest:
                    pass
            return

        if (
            callback_data.action
            == superadmin_registrations_kb.RegistrationCandidateConfirmAction.BACK
        ):
            review = await registration_review_service.get_registration_review_for_admin(
                admin_telegram_id=callback.from_user.id,
                request_id=callback_data.request_id,
            )
            await callback.answer()
            if callback.message is not None:
                await callback.message.edit_text(
                    format_registration_review(review),
                    reply_markup=superadmin_registrations_kb.registration_candidate_selection_keyboard(
                        callback_data.request_id,
                        review.candidates,
                    ),
                )
            return

        review_result = await registration_review_service.approve_registration(
            superadmin_telegram_id=callback.from_user.id,
            request_id=callback_data.request_id,
            candidate_user_id=callback_data.user_id,
        )
    except AdminAccessDeniedError:
        await callback.answer(panel_text.INSUFFICIENT_RIGHTS, show_alert=True)
        return
    except UserNotFoundError:
        await callback.answer(text.PLAYER_NOT_FOUND, show_alert=True)
        return
    except RegistrationAlreadyReviewedError:
        await callback.answer(
            text.REGISTRATION_ALREADY_REVIEWED,
            show_alert=True,
        )
        return
    except (RegistrationCandidateNotFoundError, RegistrationNotAllowedError):
        await callback.answer(text.REGISTRATION_NOT_ALLOWED, show_alert=True)
        return

    await _send_registration_review_result(
        callback=callback,
        review_result=review_result,
        result_text=text.REGISTRATION_APPROVED,
        player_text="Ваша заявка одобрена.",
        player_keyboard=user_menu_kb.main_keyboard_after_registration(),
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
    reviewed_text = text.reviewed_by_admin(
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
