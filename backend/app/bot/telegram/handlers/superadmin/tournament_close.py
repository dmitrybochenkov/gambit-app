import logging
from datetime import date

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InputMediaPhoto, Message

from app.bot.telegram.formatters import results as result_fmt
from app.bot.telegram.formatters import schedules as schedule_fmt
from app.bot.telegram.handlers.admin.shared import (
    RESULT_SUMMARY_PARSE_MODE,
)
from app.bot.telegram.handlers.admin.shared import (
    delete_callback_message as _delete_callback_message,
)
from app.bot.telegram.keyboards import labels
from app.bot.telegram.keyboards.admin import results as admin_results_kb
from app.bot.telegram.keyboards.admin import schedule as admin_schedule_kb
from app.bot.telegram.keyboards.superadmin import panel as superadmin_panel_kb
from app.bot.telegram.keyboards.superadmin import tournament_close as superadmin_tournament_close_kb
from app.bot.telegram.message_edit import (
    edit_message_if_changed,
    edit_message_text_by_id_if_changed,
)
from app.bot.telegram.states import AdminResultStates
from app.bot.telegram.texts.admin import calendar as calendar_text
from app.bot.telegram.texts.superadmin import panel as panel_text
from app.bot.telegram.texts.superadmin import tournament_close as text
from app.services.access_policy import AdminAccessDeniedError
from app.services.pagination import pagination_service
from app.services.result_service import (
    FutureTournamentCannotBeClosedError,
    ResultInvalidFundError,
    ResultService,
    ResultTournamentNotFoundError,
    ResultValidationError,
    result_service,
)
from app.services.tournament_planning_service import (
    CalendarDefaultTournamentTypeNotFoundError,
    CalendarWeeklyPlanIntegrityError,
    WeeklyPlanningStatus,
    tournament_planning_service,
)

logger = logging.getLogger(__name__)


router = Router(name="admin.tournament_close")


@router.message(F.text == labels.ADMIN_PANEL_CLOSE_TOURNAMENT)
async def show_close_tournament_flow(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return
    await state.clear()
    try:
        tournaments = await result_service.list_unclosed_tournaments_for_superadmin(
            message.from_user.id
        )
    except AdminAccessDeniedError:
        await message.answer(panel_text.INSUFFICIENT_RIGHTS)
        return

    if not tournaments:
        await message.answer(
            text.NO_READY_TOURNAMENTS,
            reply_markup=superadmin_panel_kb.superadmin_panel_keyboard(),
        )
        return

    page = pagination_service.paginate(
        tournaments,
        page=0,
        page_size=admin_results_kb.ADMIN_RESULT_PAGE_SIZE,
    )
    await message.answer(
        result_fmt.close_tournament_list(page),
        reply_markup=superadmin_tournament_close_kb.admin_close_tournament_list_keyboard(page),
    )


@router.callback_query(superadmin_tournament_close_kb.AdminCloseTournamentCallback.filter())
async def select_close_tournament_action(
    callback: CallbackQuery,
    callback_data: superadmin_tournament_close_kb.AdminCloseTournamentCallback,
    state: FSMContext,
) -> None:
    try:
        if callback_data.action == superadmin_tournament_close_kb.AdminCloseTournamentAction.CANCEL:
            await state.clear()
            await callback.answer(text.ADMIN_RESULTS_CANCELLED)
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer(
                    text.ADMIN_RESULTS_CANCELLED,
                    reply_markup=superadmin_panel_kb.superadmin_panel_keyboard(),
                )
            return

        if callback_data.action == superadmin_tournament_close_kb.AdminCloseTournamentAction.PAGE:
            tournaments = await result_service.list_unclosed_tournaments_for_superadmin(
                callback.from_user.id
            )
            page = pagination_service.paginate(
                tournaments,
                page=callback_data.page,
                page_size=admin_results_kb.ADMIN_RESULT_PAGE_SIZE,
            )
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=result_fmt.close_tournament_list(page),
                    reply_markup=superadmin_tournament_close_kb.admin_close_tournament_list_keyboard(
                        page
                    ),
                )
            return

        if callback_data.action in {
            superadmin_tournament_close_kb.AdminCloseTournamentAction.OPEN,
        }:
            await callback.answer()
            if callback.message is not None:
                await _edit_close_tournament_card(
                    callback=callback,
                    state=state,
                    tournament_id=callback_data.tournament_id,
                    page=callback_data.page,
                )
            return

        if (
            callback_data.action
            == superadmin_tournament_close_kb.AdminCloseTournamentAction.VIEW_PHOTOS
        ):
            await _send_tournament_photos(callback, callback_data.tournament_id)
            return

        if (
            callback_data.action
            == superadmin_tournament_close_kb.AdminCloseTournamentAction.CHANGE_FUND
        ):
            await _prepare_fund_input_state(
                state=state,
                superadmin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
                page=callback_data.page,
            )
            await callback.answer()
            if callback.message is not None:
                await _delete_callback_message(callback)
            return

        if (
            callback_data.action
            == superadmin_tournament_close_kb.AdminCloseTournamentAction.CONFIRM
        ):
            data = await state.get_data()
            tournament_fund = int(data["tournament_fund"])
            results = await result_service.close_tournament(
                superadmin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
                tournament_fund=tournament_fund,
            )
            await state.clear()
            await callback.answer("Турнир закрыт.")
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer(
                    result_fmt.closed_tournament(results),
                    parse_mode=RESULT_SUMMARY_PARSE_MODE,
                )
                await _send_calendar_planning_notification_after_close(
                    callback,
                    results.tournament.date,
                )
            return
    except AdminAccessDeniedError:
        await callback.answer(text.ACCESS_DENIED, show_alert=True)
        return
    except ResultInvalidFundError:
        await callback.answer(result_fmt.tournament_fund_error(), show_alert=True)
        return
    except ResultTournamentNotFoundError:
        await callback.answer(text.ADMIN_RESULTS_NOT_FOUND, show_alert=True)
        return
    except FutureTournamentCannotBeClosedError:
        await callback.answer("Будущий турнир нельзя закрыть.", show_alert=True)
        return
    except ResultValidationError as error:
        await callback.answer()
        if callback.message is not None:
            await callback.message.answer(result_fmt.close_tournament_blocked(error.errors))
        return

    await callback.answer(text.ADMIN_RESULTS_NOT_FOUND, show_alert=True)


async def _send_calendar_planning_notification_after_close(
    callback: CallbackQuery,
    closed_tournament_date: date,
) -> None:
    if callback.message is None:
        return
    try:
        planning = await tournament_planning_service.inspect_after_tournament_close(
            callback.from_user.id,
            closed_tournament_date,
        )
    except (
        AdminAccessDeniedError,
        CalendarDefaultTournamentTypeNotFoundError,
        CalendarWeeklyPlanIntegrityError,
    ):
        logger.exception("Failed to inspect weekly tournament planning after close")
        return

    if planning.status == WeeklyPlanningStatus.READY and planning.plan is not None:
        await callback.message.answer(calendar_text.ADMIN_CALENDAR_TOURNAMENT_WEEK_EMPTY)
        await callback.message.answer(
            schedule_fmt.plan_preview(planning.plan),
            reply_markup=admin_schedule_kb.manual_tournaments_plan_keyboard(planning.plan),
        )


async def _send_close_tournament_card(
    *,
    message: Message,
    state: FSMContext,
    superadmin_telegram_id: int,
    tournament_id: int,
    page: int,
) -> None:
    results = await result_service.get_closeable_tournament_results(
        superadmin_telegram_id=superadmin_telegram_id,
        tournament_id=tournament_id,
    )
    readiness = await result_service.get_close_readiness(
        superadmin_telegram_id=superadmin_telegram_id,
        tournament_id=tournament_id,
    )
    if not readiness.is_ready:
        await state.clear()
        await message.answer(
            result_fmt.close_tournament_blocked(readiness.reasons),
            reply_markup=superadmin_tournament_close_kb.admin_close_tournament_cancel_keyboard(
                tournament_id=tournament_id,
                page=page,
            ),
        )
        return
    sent_message = await message.answer(
        result_fmt.close_tournament_card(results),
        reply_markup=superadmin_tournament_close_kb.admin_close_tournament_card_keyboard(
            tournament_id=tournament_id,
            page=page,
        ),
        parse_mode=RESULT_SUMMARY_PARSE_MODE,
    )
    await _set_fund_input_state(
        state,
        tournament_id=tournament_id,
        page=page,
        prompt_message=sent_message,
    )


async def _edit_close_tournament_card(
    *,
    callback: CallbackQuery,
    state: FSMContext,
    tournament_id: int,
    page: int,
) -> None:
    results = await result_service.get_closeable_tournament_results(
        superadmin_telegram_id=callback.from_user.id,
        tournament_id=tournament_id,
    )
    readiness = await result_service.get_close_readiness(
        superadmin_telegram_id=callback.from_user.id,
        tournament_id=tournament_id,
    )
    if not readiness.is_ready:
        await state.clear()
        await edit_message_if_changed(
            callback.message,
            text=result_fmt.close_tournament_blocked(readiness.reasons),
            reply_markup=superadmin_tournament_close_kb.admin_close_tournament_cancel_keyboard(
                tournament_id=tournament_id,
                page=page,
            ),
        )
        return
    await edit_message_if_changed(
        callback.message,
        text=result_fmt.close_tournament_card(results),
        reply_markup=superadmin_tournament_close_kb.admin_close_tournament_card_keyboard(
            tournament_id=tournament_id,
            page=page,
        ),
        parse_mode=RESULT_SUMMARY_PARSE_MODE,
    )
    await _set_fund_input_state(
        state,
        tournament_id=tournament_id,
        page=page,
        prompt_message=callback.message,
    )


async def _prepare_fund_input_state(
    *,
    state: FSMContext,
    superadmin_telegram_id: int,
    tournament_id: int,
    page: int,
) -> None:
    errors = await result_service.validate_closeable_results(
        superadmin_telegram_id=superadmin_telegram_id,
        tournament_id=tournament_id,
    )
    if errors:
        raise ResultValidationError(errors)
    await _set_fund_input_state(state, tournament_id=tournament_id, page=page)


async def _set_fund_input_state(
    state: FSMContext,
    *,
    tournament_id: int,
    page: int,
    prompt_message: Message | None = None,
) -> None:
    await state.clear()
    await state.set_state(AdminResultStates.entering_tournament_fund)
    data: dict[str, int] = {
        "close_tournament_id": tournament_id,
        "close_tournament_page": page,
    }
    identity = _message_identity(prompt_message)
    if identity is not None:
        chat_id, message_id = identity
        data["close_tournament_prompt_chat_id"] = chat_id
        data["close_tournament_prompt_message_id"] = message_id
    await state.update_data(**data)


@router.message(AdminResultStates.entering_tournament_fund)
async def enter_tournament_fund(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return

    data = await state.get_data()
    tournament_id = int(data["close_tournament_id"])
    page_number = int(data.get("close_tournament_page", 0))
    try:
        tournament_fund = ResultService.validate_tournament_fund(int(message.text or ""))
        results = await result_service.get_closeable_tournament_results(
            superadmin_telegram_id=message.from_user.id,
            tournament_id=tournament_id,
        )
    except AdminAccessDeniedError:
        await state.clear()
        await message.answer(text.ACCESS_DENIED)
        return
    except ResultTournamentNotFoundError:
        await state.clear()
        await message.answer(text.ADMIN_RESULTS_NOT_FOUND)
        return
    except FutureTournamentCannotBeClosedError:
        await state.clear()
        await message.answer("Будущий турнир нельзя закрыть.")
        return
    except (ValueError, ResultInvalidFundError):
        await message.answer(
            result_fmt.tournament_fund_error_prompt(),
            reply_markup=superadmin_tournament_close_kb.admin_close_tournament_fund_error_keyboard(
                tournament_id=tournament_id,
                page=page_number,
            ),
        )
        return

    await state.update_data(tournament_fund=int(tournament_fund))
    await state.set_state(None)
    await _replace_close_preview_with_fund_prompt(message, data)
    await message.answer(
        result_fmt.close_tournament_confirmation(results, tournament_fund),
        reply_markup=superadmin_tournament_close_kb.admin_close_tournament_confirmation_keyboard(
            tournament_id=tournament_id,
            page=page_number,
            photo_count=results.photo_count,
        ),
        parse_mode=RESULT_SUMMARY_PARSE_MODE,
    )


async def _send_tournament_photos(
    callback: CallbackQuery,
    tournament_id: int,
) -> None:
    try:
        photos = await result_service.list_tournament_photos(
            admin_telegram_id=callback.from_user.id,
            tournament_id=tournament_id,
        )
    except AdminAccessDeniedError:
        await callback.answer(text.ACCESS_DENIED, show_alert=True)
        return
    except ResultTournamentNotFoundError:
        await callback.answer(text.ADMIN_RESULTS_NOT_FOUND, show_alert=True)
        return
    if not photos:
        await callback.answer("Фото турнира не добавлены.", show_alert=True)
        return
    await callback.answer()
    if callback.message is None:
        return
    if len(photos) == 1:
        await callback.message.answer_photo(photos[0].telegram_file_id)
        return
    await callback.message.answer_media_group(
        [InputMediaPhoto(media=photo.telegram_file_id) for photo in photos]
    )


def _message_identity(message: Message | None) -> tuple[int, int] | None:
    if message is None:
        return None
    chat_id = getattr(getattr(message, "chat", None), "id", None)
    message_id = getattr(message, "message_id", None)
    if isinstance(chat_id, int) and isinstance(message_id, int):
        return chat_id, message_id
    return None


async def _replace_close_preview_with_fund_prompt(
    message: Message,
    data: dict[str, object],
) -> None:
    chat_id = data.get("close_tournament_prompt_chat_id")
    message_id = data.get("close_tournament_prompt_message_id")
    if not isinstance(chat_id, int) or not isinstance(message_id, int):
        return
    await edit_message_text_by_id_if_changed(
        message.bot,
        chat_id=chat_id,
        message_id=message_id,
        text=result_fmt.tournament_fund_prompt(),
        reply_markup=None,
    )
