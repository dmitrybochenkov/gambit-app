import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from app.bot.telegram.handlers.admin.shared import (
    delete_callback_message as _delete_callback_message,
)
from app.bot.telegram.keyboards import labels
from app.bot.telegram.keyboards.superadmin import panel as superadmin_panel_kb
from app.bot.telegram.keyboards.superadmin import registrations as superadmin_registrations_kb
from app.bot.telegram.keyboards.user import menu as user_menu_kb
from app.bot.telegram.message_edit import edit_message_if_changed
from app.bot.telegram.notifications import format_registration_review
from app.bot.telegram.texts.superadmin import panel as panel_text
from app.bot.telegram.texts.superadmin import registrations as text
from app.bot.telegram.texts.user import registration as user_registration_text
from app.services.access_policy import AdminAccessDeniedError
from app.services.dto.registrations import RegistrationReviewResultView
from app.services.pagination import Page
from app.services.registration_review_service import (
    TournamentRegistrationsUnavailableError,
    registration_review_service,
)
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
        overview = await registration_review_service.get_registrations_overview_for_superadmin(
            message.from_user.id,
        )
    except AdminAccessDeniedError:
        await message.answer(panel_text.INSUFFICIENT_RIGHTS)
        return

    if overview.has_user_registrations and overview.has_tournament_registrations:
        await message.answer(
            text.REGISTRATION_LIST_TITLE,
            reply_markup=superadmin_registrations_kb.registrations_hub_keyboard(),
        )
        return
    if overview.has_user_registrations:
        page = await _get_pending_reviews_page(message.from_user.id, page=0)
        await _answer_pending_reviews(message, page)
        return
    if overview.has_tournament_registrations:
        await message.answer(
            text.tournament_registrations_overview(overview.tournaments),
            reply_markup=superadmin_registrations_kb.tournament_registrations_keyboard(
                overview.tournaments,
                can_go_back=False,
            ),
        )
        return

    await message.answer(text.REGISTRATIONS_EMPTY)


@router.callback_query(superadmin_registrations_kb.RegistrationsHubCallback.filter())
async def registrations_hub(
    callback: CallbackQuery,
    callback_data: superadmin_registrations_kb.RegistrationsHubCallback,
) -> None:
    try:
        if callback_data.action == superadmin_registrations_kb.RegistrationsHubAction.CANCEL:
            await callback.answer(text.REGISTRATION_CANCELLED)
            await _return_to_superadmin_menu(callback)
            return

        if callback_data.action == superadmin_registrations_kb.RegistrationsHubAction.USER_REQUESTS:
            page = await _get_pending_reviews_page(callback.from_user.id, page=0)
            await callback.answer()
            await _edit_pending_reviews(callback, page)
            return

        overview = await registration_review_service.get_registrations_overview_for_superadmin(
            callback.from_user.id,
        )
        await callback.answer()
        if callback_data.action == superadmin_registrations_kb.RegistrationsHubAction.BACK:
            await _edit_registrations_hub(callback, overview)
            return

        await _edit_tournament_registrations_overview(
            callback,
            overview.tournaments,
            can_go_back=True,
        )
    except AdminAccessDeniedError:
        await callback.answer(panel_text.INSUFFICIENT_RIGHTS, show_alert=True)


@router.callback_query(superadmin_registrations_kb.TournamentRegistrationsCallback.filter())
async def tournament_registrations(
    callback: CallbackQuery,
    callback_data: superadmin_registrations_kb.TournamentRegistrationsCallback,
) -> None:
    can_go_back = bool(callback_data.can_go_back)
    try:
        if callback_data.action == superadmin_registrations_kb.TournamentRegistrationsAction.BACK:
            overview = await registration_review_service.get_registrations_overview_for_superadmin(
                callback.from_user.id,
            )
            await callback.answer()
            await _edit_tournament_registrations_overview(
                callback,
                overview.tournaments,
                can_go_back=can_go_back,
            )
            return

        detail = (
            await registration_review_service.get_tournament_registrations_detail_for_superadmin(
                callback.from_user.id,
                callback_data.tournament_id,
            )
        )
    except AdminAccessDeniedError:
        await callback.answer(panel_text.INSUFFICIENT_RIGHTS, show_alert=True)
        return
    except TournamentRegistrationsUnavailableError:
        await callback.answer(text.TOURNAMENT_REGISTRATIONS_UNAVAILABLE, show_alert=True)
        overview = await registration_review_service.get_registrations_overview_for_superadmin(
            callback.from_user.id,
        )
        await _edit_tournament_registrations_overview(
            callback,
            overview.tournaments,
            can_go_back=can_go_back,
        )
        return

    await callback.answer()
    if callback.message is not None:
        await edit_message_if_changed(
            callback.message,
            text=text.tournament_registrations_detail(detail),
            reply_markup=superadmin_registrations_kb.tournament_registrations_detail_keyboard(
                can_go_back=can_go_back,
            ),
        )


@router.callback_query(superadmin_registrations_kb.RegistrationListCallback.filter())
async def review_registration_list(
    callback: CallbackQuery,
    callback_data: superadmin_registrations_kb.RegistrationListCallback,
) -> None:
    try:
        if callback_data.action == superadmin_registrations_kb.RegistrationListAction.CANCEL:
            await callback.answer(text.REGISTRATION_CANCELLED)
            await _return_to_superadmin_menu(callback)
            return

        if callback_data.action == superadmin_registrations_kb.RegistrationListAction.OPEN:
            review = await _get_review(callback.from_user.id, callback_data.request_id)
            await callback.answer()
            if callback.message is not None:
                await _edit_registration_review(callback, review, callback_data.page)
            return

        page = await _get_pending_reviews_page(callback.from_user.id, page=callback_data.page)
        await callback.answer()
        await _edit_pending_reviews(callback, page)
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
            review = await _get_review(callback.from_user.id, callback_data.request_id)
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=format_registration_review(review),
                    reply_markup=superadmin_registrations_kb.registration_candidate_selection_keyboard(
                        callback_data.request_id,
                        review.candidates,
                        callback_data.page,
                    ),
                )
            return

        if callback_data.action == superadmin_registrations_kb.RegistrationReviewAction.BACK:
            page = await _get_pending_reviews_page(
                callback.from_user.id,
                page=callback_data.page,
            )
            await callback.answer()
            await _edit_pending_reviews(callback, page)
            return

        if callback_data.action == superadmin_registrations_kb.RegistrationReviewAction.APPROVE:
            review_result = await registration_review_service.approve_registration(
                superadmin_telegram_id=callback.from_user.id,
                request_id=callback_data.request_id,
            )
            result_text = text.REGISTRATION_APPROVED
            player_text = user_registration_text.REGISTRATION_APPROVED
            player_keyboard = user_menu_kb.main_keyboard_after_registration()
        elif callback_data.action == superadmin_registrations_kb.RegistrationReviewAction.CANCEL:
            await callback.answer(text.REGISTRATION_CANCELLED)
            await _return_to_superadmin_menu(callback)
            return
        else:
            review_result = await registration_review_service.reject_registration(
                superadmin_telegram_id=callback.from_user.id,
                request_id=callback_data.request_id,
            )
            result_text = text.REGISTRATION_REJECTED
            player_text = user_registration_text.REGISTRATION_REJECTED
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
        page=callback_data.page,
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

    await callback.answer(text.REGISTRATION_CANDIDATE_SELECTED)
    if callback.message is not None:
        await edit_message_if_changed(
            callback.message,
            text=text.registration_candidate_confirmation(
                review.selected_candidate.user.display_name
                if review.selected_candidate is not None
                else ""
            ),
            reply_markup=superadmin_registrations_kb.registration_candidate_confirmation_keyboard(
                callback_data.request_id,
                callback_data.user_id,
                callback_data.page,
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
            await _return_to_superadmin_menu(callback)
            return

        if (
            callback_data.action
            == superadmin_registrations_kb.RegistrationCandidateConfirmAction.BACK
        ):
            review = await _get_review(callback.from_user.id, callback_data.request_id)
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=format_registration_review(review),
                    reply_markup=superadmin_registrations_kb.registration_candidate_selection_keyboard(
                        callback_data.request_id,
                        review.candidates,
                        callback_data.page,
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
        player_text=user_registration_text.REGISTRATION_APPROVED,
        player_keyboard=user_menu_kb.main_keyboard_after_registration(),
        page=callback_data.page,
    )


async def _send_registration_review_result(
    callback: CallbackQuery,
    review_result: RegistrationReviewResultView,
    result_text: str,
    player_text: str,
    player_keyboard: object,
    page: int,
) -> None:
    await callback.answer(result_text)
    admin_review_text = callback.message.text if callback.message is not None else ""
    reviewed_text = text.reviewed_by_admin(
        review_text=admin_review_text,
        result_text=result_text,
        admin_name=callback.from_user.full_name,
    )
    if callback.message is not None:
        updated_page = await _get_pending_reviews_page(callback.from_user.id, page=page)
        await _edit_pending_reviews(callback, updated_page)

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


async def _get_pending_reviews_page(
    superadmin_telegram_id: int,
    *,
    page: int,
) -> Page:
    return await registration_review_service.list_pending_reviews_page_for_superadmin(
        superadmin_telegram_id,
        page=page,
        page_size=superadmin_registrations_kb.REGISTRATION_LIST_PAGE_SIZE,
    )


async def _get_review(superadmin_telegram_id: int, request_id: int):
    return await registration_review_service.get_registration_review_for_admin(
        admin_telegram_id=superadmin_telegram_id,
        request_id=request_id,
    )


async def _answer_pending_reviews(message: Message, page: Page) -> None:
    if not page.items:
        await message.answer(
            text.NO_PENDING_REGISTRATIONS,
            reply_markup=superadmin_panel_kb.superadmin_panel_keyboard(),
        )
        return

    await message.answer(
        text.registration_list(page),
        reply_markup=superadmin_registrations_kb.registration_list_keyboard(page),
    )


async def _edit_pending_reviews(callback: CallbackQuery, page: Page) -> None:
    if callback.message is None:
        return
    if not page.items:
        await edit_message_if_changed(
            callback.message,
            text=text.NO_PENDING_REGISTRATIONS,
            reply_markup=None,
        )
        await callback.message.answer(
            panel_text.SUPERADMIN_PANEL_WELCOME,
            reply_markup=superadmin_panel_kb.superadmin_panel_keyboard(),
        )
        return

    await edit_message_if_changed(
        callback.message,
        text=text.registration_list(page),
        reply_markup=superadmin_registrations_kb.registration_list_keyboard(page),
    )


async def _edit_registrations_hub(callback: CallbackQuery, overview: object) -> None:
    if callback.message is None:
        return
    if overview.has_user_registrations and overview.has_tournament_registrations:
        await edit_message_if_changed(
            callback.message,
            text=text.REGISTRATION_LIST_TITLE,
            reply_markup=superadmin_registrations_kb.registrations_hub_keyboard(),
        )
        return
    if overview.has_user_registrations:
        page = await _get_pending_reviews_page(callback.from_user.id, page=0)
        await _edit_pending_reviews(callback, page)
        return
    if overview.has_tournament_registrations:
        await _edit_tournament_registrations_overview(
            callback,
            overview.tournaments,
            can_go_back=False,
        )
        return
    await edit_message_if_changed(
        callback.message,
        text=text.REGISTRATIONS_EMPTY,
        reply_markup=superadmin_registrations_kb.tournament_registrations_keyboard(
            [],
            can_go_back=False,
        ),
    )


async def _edit_tournament_registrations_overview(
    callback: CallbackQuery,
    tournaments: list[object],
    *,
    can_go_back: bool,
) -> None:
    if callback.message is None:
        return
    overview_text = (
        text.tournament_registrations_overview(tournaments)
        if tournaments
        else text.empty_tournament_registrations_overview()
    )
    await edit_message_if_changed(
        callback.message,
        text=overview_text,
        reply_markup=superadmin_registrations_kb.tournament_registrations_keyboard(
            tournaments,
            can_go_back=can_go_back,
        ),
    )


async def _edit_registration_review(
    callback: CallbackQuery,
    review: object,
    page: int,
) -> None:
    if callback.message is None:
        return
    await edit_message_if_changed(
        callback.message,
        text=format_registration_review(review),
        reply_markup=superadmin_registrations_kb.registration_review_keyboard_for_review(
            review,
            page,
        ),
    )


async def _return_to_superadmin_menu(callback: CallbackQuery) -> None:
    if callback.message is not None:
        await _delete_callback_message(callback)
        await callback.message.answer(
            panel_text.SUPERADMIN_PANEL_WELCOME,
            reply_markup=superadmin_panel_kb.superadmin_panel_keyboard(),
        )
