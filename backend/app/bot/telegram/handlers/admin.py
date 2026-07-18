import re
from datetime import date

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from app.bot.telegram import keyboards, texts
from app.bot.telegram.formatters import (
    format_admin_calendar_prompt,
    format_manual_season_prompt,
)
from app.bot.telegram.notifications import format_registration_review
from app.bot.telegram.states import CalendarSeasonEditStates
from app.services.calendar_service import (
    CalendarPromptAction,
    CalendarPromptAlreadyResolvedError,
    CalendarPromptEmptyError,
    CalendarPromptInvalidPayloadError,
    CalendarPromptNotFoundError,
    calendar_service,
)
from app.services.dto import RegistrationReviewResultView
from app.services.pagination import pagination_service
from app.services.player_service import (
    AdminAccessDeniedError,
    PlayerNotFoundError,
    RegistrationAlreadyReviewedError,
    RegistrationMatchNotFoundError,
    player_service,
)

router = Router(name="admin")
SEASON_EDIT_PROMPTS = {
    keyboards.SeasonEditAction.NAME: texts.admin.ADMIN_CALENDAR_ENTER_SEASON_NAME,
    keyboards.SeasonEditAction.STARTS_AT: texts.admin.ADMIN_CALENDAR_ENTER_SEASON_START,
    keyboards.SeasonEditAction.ENDS_AT: texts.admin.ADMIN_CALENDAR_ENTER_SEASON_END,
}


@router.message(Command("admin"))
@router.message(F.text == keyboards.MAIN_ADMIN)
async def open_admin_panel(message: Message) -> None:
    if message.from_user is None:
        return

    try:
        await player_service.get_admin_panel_for_admin(message.from_user.id)
    except AdminAccessDeniedError:
        await message.answer(texts.admin.ACCESS_DENIED)
        return

    await message.answer(
        texts.admin.ADMIN_PANEL_WELCOME,
        reply_markup=keyboards.admin_panel_keyboard(),
    )


@router.message(F.text == keyboards.ADMIN_PANEL_REGISTRATIONS)
async def show_pending_registrations(message: Message) -> None:
    if message.from_user is None:
        return

    try:
        admin_panel = await player_service.get_admin_panel_for_admin(message.from_user.id)
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
            review = await player_service.get_registration_review_for_admin(
                admin_telegram_id=callback.from_user.id,
                pending_player_id=callback_data.player_id,
            )
            await callback.answer()
            if callback.message is not None:
                await callback.message.edit_text(
                    format_registration_review(review.player, review.matches),
                    reply_markup=keyboards.registration_review_keyboard(
                        review.player.id,
                        has_matches=bool(review.matches),
                    ),
                )
            return

        admin_panel = await player_service.get_admin_panel_for_admin(callback.from_user.id)
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
    except (PlayerNotFoundError, RegistrationAlreadyReviewedError):
        await callback.answer(
            texts.admin.REGISTRATION_ALREADY_REVIEWED,
            show_alert=True,
        )


@router.message(F.text == keyboards.ADMIN_PANEL_EXIT)
async def exit_admin_panel(message: Message) -> None:
    if message.from_user is None:
        return

    try:
        admin_panel = await player_service.get_admin_panel_for_admin(message.from_user.id)
    except AdminAccessDeniedError:
        await message.answer(texts.admin.ACCESS_DENIED)
        return

    await message.answer(
        texts.admin.ADMIN_PANEL_EXITED,
        reply_markup=keyboards.main_keyboard_for_player(admin_panel.admin),
    )


@router.message(F.text == keyboards.ADMIN_PANEL_CALENDAR)
async def open_admin_calendar(message: Message) -> None:
    if message.from_user is None:
        return

    try:
        await player_service.require_superadmin(message.from_user.id)
    except AdminAccessDeniedError:
        await message.answer(texts.admin.ACCESS_DENIED)
        return

    await message.answer(
        texts.admin.ADMIN_CALENDAR_PROMPT,
        reply_markup=keyboards.admin_calendar_keyboard(),
    )


@router.callback_query(keyboards.RegistrationReviewCallback.filter())
async def review_registration(
    callback: CallbackQuery,
    callback_data: keyboards.RegistrationReviewCallback,
) -> None:
    try:
        if callback_data.action in {
            keyboards.RegistrationReviewAction.APPROVE,
            keyboards.RegistrationReviewAction.APPROVE_NEW,
        }:
            if callback_data.action == keyboards.RegistrationReviewAction.APPROVE:
                matches = await player_service.get_registration_matches_for_admin(
                    admin_telegram_id=callback.from_user.id,
                    pending_player_id=callback_data.player_id,
                )
                if len(matches) > 1:
                    await callback.answer()
                    if callback.message is not None:
                        await callback.message.edit_reply_markup(
                            reply_markup=keyboards.registration_match_selection_keyboard(
                                callback_data.player_id,
                                matches,
                            )
                        )
                    return

            review_result = await player_service.approve_registration(
                admin_telegram_id=callback.from_user.id,
                player_id=callback_data.player_id,
                use_registration_match=(
                    callback_data.action == keyboards.RegistrationReviewAction.APPROVE
                ),
            )
            result_text = (
                texts.admin.REGISTRATION_APPROVED_AS_NEW
                if callback_data.action == keyboards.RegistrationReviewAction.APPROVE_NEW
                else texts.admin.REGISTRATION_APPROVED
            )
            player_text = texts.admin.registration_approved_message(
                review_result.player.display_name
            )
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
            review_result = await player_service.reject_registration(
                admin_telegram_id=callback.from_user.id,
                player_id=callback_data.player_id,
            )
            result_text = texts.admin.REGISTRATION_REJECTED
            player_text = texts.admin.REGISTRATION_REJECTION_MESSAGE
            player_keyboard = ReplyKeyboardRemove()
    except AdminAccessDeniedError:
        await callback.answer(texts.admin.ACCESS_DENIED, show_alert=True)
        return
    except PlayerNotFoundError:
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


@router.callback_query(keyboards.RegistrationMatchSelectionCallback.filter())
async def select_registration_match(
    callback: CallbackQuery,
    callback_data: keyboards.RegistrationMatchSelectionCallback,
) -> None:
    try:
        review_result = await player_service.approve_registration(
            admin_telegram_id=callback.from_user.id,
            player_id=callback_data.player_id,
            historical_player_id=callback_data.historical_player_id,
        )
    except AdminAccessDeniedError:
        await callback.answer(texts.admin.ACCESS_DENIED, show_alert=True)
        return
    except PlayerNotFoundError:
        await callback.answer(texts.admin.PLAYER_NOT_FOUND, show_alert=True)
        return
    except (RegistrationAlreadyReviewedError, RegistrationMatchNotFoundError):
        await callback.answer(
            texts.admin.REGISTRATION_ALREADY_REVIEWED,
            show_alert=True,
        )
        return

    await _send_registration_review_result(
        callback=callback,
        review_result=review_result,
        result_text=texts.admin.REGISTRATION_APPROVED,
        player_text=texts.admin.registration_approved_message(
            review_result.player.display_name
        ),
        player_keyboard=keyboards.main_keyboard_after_registration(),
    )


async def _send_registration_review_result(
    callback: CallbackQuery,
    review_result: RegistrationReviewResultView,
    result_text: str,
    player_text: str,
    player_keyboard: object,
) -> None:
    await callback.answer(result_text)
    player = review_result.player
    admin_review_text = callback.message.text if callback.message is not None else ""
    reviewed_text = texts.admin.reviewed_by_admin(
        review_text=admin_review_text or format_registration_review(player),
        result_text=result_text,
        admin_name=callback.from_user.full_name,
    )
    if callback.message is not None:
        try:
            await callback.message.edit_text(reviewed_text)
        except TelegramBadRequest:
            pass

    for admin in review_result.admins:
        if admin.telegram_id == callback.from_user.id:
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
            chat_id=player.telegram_id,
            text=player_text,
            reply_markup=player_keyboard,
        )
    except (TelegramBadRequest, TelegramForbiddenError):
        pass


@router.callback_query(keyboards.CalendarPromptCallback.filter())
async def review_calendar_prompt(
    callback: CallbackQuery,
    callback_data: keyboards.CalendarPromptCallback,
    state: FSMContext,
) -> None:
    action = CalendarPromptAction(callback_data.action.value)
    try:
        await player_service.require_superadmin(callback.from_user.id)
        if callback_data.action == keyboards.CalendarPromptAction.EDIT:
            await state.clear()
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer(
                    texts.admin.ADMIN_CALENDAR_EDIT_MENU,
                    reply_markup=keyboards.season_edit_keyboard(callback_data.prompt_id),
                )
            await callback.answer()
            return

        await state.clear()
        resolved_prompt = await calendar_service.resolve_prompt(
            prompt_id=callback_data.prompt_id,
            admin_telegram_id=callback.from_user.id,
            action=action,
        )
    except AdminAccessDeniedError:
        await callback.answer(texts.admin.ACCESS_DENIED, show_alert=True)
        return
    except CalendarPromptNotFoundError:
        await callback.answer(texts.admin.CALENDAR_PROMPT_NOT_FOUND, show_alert=True)
        return
    except CalendarPromptAlreadyResolvedError:
        await callback.answer(
            texts.admin.CALENDAR_PROMPT_ALREADY_RESOLVED,
            show_alert=True,
        )
        return

    if callback_data.action == keyboards.CalendarPromptAction.CONFIRM:
        result_text = (
            texts.admin.ADMIN_CALENDAR_SEASON_CREATED
            if resolved_prompt.kind == "season_proposal"
            else texts.admin.ADMIN_CALENDAR_TOURNAMENTS_CREATED
        )
    elif callback_data.action == keyboards.CalendarPromptAction.CANCEL:
        result_text = texts.admin.CALENDAR_PROMPT_CANCELLED
    else:
        result_text = texts.admin.CALENDAR_PROMPT_NEEDS_CHANGES

    await callback.answer(result_text)
    if callback.message is not None:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest:
            pass
        await callback.message.answer(
            texts.admin.calendar_reviewed_by_admin(
                prompt_text=callback.message.text or "",
                result_text=result_text,
                admin_name=callback.from_user.full_name,
            )
        )


@router.callback_query(keyboards.AdminCalendarCallback.filter())
async def select_admin_calendar_section(
    callback: CallbackQuery,
    callback_data: keyboards.AdminCalendarCallback,
) -> None:
    try:
        await player_service.require_superadmin(callback.from_user.id)
    except AdminAccessDeniedError:
        await callback.answer(texts.admin.ACCESS_DENIED, show_alert=True)
        return

    await _delete_callback_message(callback)

    if callback_data.action == keyboards.AdminCalendarAction.CANCEL:
        await callback.answer(texts.admin.ADMIN_CALENDAR_CANCELLED)
        if callback.message is not None:
            await callback.message.answer(texts.admin.ADMIN_CALENDAR_CANCELLED)
        return

    if callback_data.action == keyboards.AdminCalendarAction.SEASONS:
        try:
            prompt = await calendar_service.get_or_create_manual_season_prompt()
        except CalendarPromptEmptyError:
            await callback.answer(texts.admin.ADMIN_CALENDAR_EMPTY_SEASONS)
            if callback.message is not None:
                await callback.message.answer(texts.admin.ADMIN_CALENDAR_EMPTY_SEASONS)
            return

        await callback.answer()
        if callback.message is not None:
            await callback.message.answer(
                format_manual_season_prompt(prompt),
                reply_markup=keyboards.manual_season_prompt_keyboard(prompt.id),
            )
        return

    try:
        prompt = await calendar_service.get_or_create_manual_tournaments_prompt()
    except CalendarPromptEmptyError:
        await callback.answer(texts.admin.ADMIN_CALENDAR_EMPTY_TOURNAMENTS)
        if callback.message is not None:
            await callback.message.answer(texts.admin.ADMIN_CALENDAR_EMPTY_TOURNAMENTS)
        return

    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(
            format_admin_calendar_prompt(prompt),
            reply_markup=keyboards.calendar_prompt_keyboard(prompt.id),
        )


@router.callback_query(keyboards.SeasonEditCallback.filter())
async def select_season_edit_field(
    callback: CallbackQuery,
    callback_data: keyboards.SeasonEditCallback,
    state: FSMContext,
) -> None:
    try:
        await player_service.require_superadmin(callback.from_user.id)
    except AdminAccessDeniedError:
        await callback.answer(texts.admin.ACCESS_DENIED, show_alert=True)
        return

    await _delete_callback_message(callback)
    if callback_data.action == keyboards.SeasonEditAction.CANCEL:
        await state.clear()
        await callback.answer(texts.admin.ADMIN_CALENDAR_CANCELLED)
        if callback.message is not None:
            await callback.message.answer(texts.admin.ADMIN_CALENDAR_CANCELLED)
        return

    await state.set_state(CalendarSeasonEditStates.entering_value)
    await state.update_data(
        season_prompt_id=callback_data.prompt_id,
        season_edit_field=callback_data.action.value,
    )
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(SEASON_EDIT_PROMPTS[callback_data.action])


@router.message(CalendarSeasonEditStates.entering_value)
async def enter_season_edit_value(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return

    try:
        await player_service.require_superadmin(message.from_user.id)
    except AdminAccessDeniedError:
        await state.clear()
        await message.answer(texts.admin.ACCESS_DENIED)
        return

    data = await state.get_data()
    prompt_id = int(data["season_prompt_id"])
    field = keyboards.SeasonEditAction(data["season_edit_field"])
    value = " ".join((message.text or "").split())
    if not value:
        await message.answer(SEASON_EDIT_PROMPTS[field])
        return

    try:
        if field == keyboards.SeasonEditAction.NAME:
            prompt = await calendar_service.update_season_prompt(
                prompt_id=prompt_id,
                name=value,
            )
        elif field == keyboards.SeasonEditAction.STARTS_AT:
            prompt = await calendar_service.update_season_prompt(
                prompt_id=prompt_id,
                starts_at=parse_admin_date(value),
            )
        else:
            prompt = await calendar_service.update_season_prompt(
                prompt_id=prompt_id,
                ends_at=parse_admin_date(value),
            )
    except CalendarPromptInvalidPayloadError:
        await message.answer(texts.admin.ADMIN_CALENDAR_INVALID_PERIOD)
        return
    except ValueError:
        await message.answer(texts.admin.ADMIN_CALENDAR_INVALID_DATE)
        return
    except (CalendarPromptNotFoundError, CalendarPromptAlreadyResolvedError):
        await state.clear()
        await message.answer(texts.admin.CALENDAR_PROMPT_ALREADY_RESOLVED)
        return

    await state.clear()
    await message.answer(
        format_manual_season_prompt(prompt),
        reply_markup=keyboards.manual_season_prompt_keyboard(prompt.id),
    )


async def _delete_callback_message(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest:
            pass


def parse_admin_date(value: str) -> date:
    match = re.fullmatch(r"(\d{1,2})\.(\d{2})\.(\d{4})", value.strip())
    if match is None:
        raise ValueError
    day, month, year = (int(part) for part in match.groups())
    return date(year, month, day)
