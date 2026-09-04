import logging
from datetime import date

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.telegram.formatters import tournaments as tournament_fmt
from app.bot.telegram.handlers.superadmin.navigation import send_superadmin_panel
from app.bot.telegram.keyboards import labels
from app.bot.telegram.keyboards.superadmin import tournaments as superadmin_tournaments_kb
from app.bot.telegram.message_edit import edit_message_if_changed
from app.bot.telegram.texts.superadmin import panel as panel_text
from app.bot.telegram.texts.superadmin import tournaments as text
from app.services.access_policy import AdminAccessDeniedError
from app.services.result_service import (
    FutureTournamentCannotBeClosedError,
    ResultPlayerRewardConflictError,
    ResultTournamentNotFoundError,
    ResultUserNotFoundError,
    result_service,
)
from app.services.tournament_participant_service import tournament_participant_service
from app.services.tournament_planning_service import (
    CalendarDefaultTournamentTypeNotFoundError,
    CalendarNoUnapprovedTournamentsError,
    CalendarTournamentDateAlreadyExistsError,
    CalendarTournamentNotEditableError,
    CalendarTournamentNotFoundError,
    CalendarTournamentTypeNotFoundError,
    CalendarWeeklyPlanIntegrityError,
    CalendarWeekNotEmptyError,
    tournament_planning_service,
)

logger = logging.getLogger(__name__)

router = Router(name="superadmin.tournaments")


@router.message(F.text == labels.SUPERADMIN_PANEL_TOURNAMENTS)
async def open_tournament_hub(message: Message) -> None:
    if message.from_user is None:
        return

    try:
        hub = await tournament_planning_service.get_superadmin_tournament_hub(message.from_user.id)
    except AdminAccessDeniedError:
        await message.answer(panel_text.INSUFFICIENT_RIGHTS)
        return

    await message.answer(
        text.TOURNAMENT_HUB_TITLE,
        reply_markup=superadmin_tournaments_kb.tournament_hub_keyboard(hub.open_tournaments_count),
    )


@router.callback_query(superadmin_tournaments_kb.SuperadminTournamentHubCallback.filter())
async def select_tournament_hub_action(
    callback: CallbackQuery,
    callback_data: superadmin_tournaments_kb.SuperadminTournamentHubCallback,
    state: FSMContext,
) -> None:
    try:
        if callback_data.action == superadmin_tournaments_kb.SuperadminTournamentHubAction.BACK:
            await state.clear()
            await callback.answer()
            if callback.message is not None:
                await send_superadmin_panel(
                    callback.message,
                    superadmin_telegram_id=callback.from_user.id,
                    text=panel_text.SUPERADMIN_PANEL_WELCOME,
                )
            return

        await tournament_planning_service.get_superadmin_tournament_hub(callback.from_user.id)
    except AdminAccessDeniedError:
        await state.clear()
        await callback.answer(panel_text.INSUFFICIENT_RIGHTS, show_alert=True)
        return

    if callback_data.action == superadmin_tournaments_kb.SuperadminTournamentHubAction.CALENDAR:
        await _edit_calendar_month(callback, state=state)
        return

    if callback_data.action == superadmin_tournaments_kb.SuperadminTournamentHubAction.OPEN:
        await _edit_open_tournament_list(callback, page=0)
        return

    from app.bot.telegram.handlers.superadmin import (
        tournament_close as superadmin_close_handlers,
    )

    await superadmin_close_handlers.open_closed_tournament_list_from_tournament_hub(
        callback=callback,
        page=0,
    )


@router.callback_query(superadmin_tournaments_kb.SuperadminTournamentCalendarCallback.filter())
async def select_tournament_calendar_action(
    callback: CallbackQuery,
    callback_data: superadmin_tournaments_kb.SuperadminTournamentCalendarCallback,
    state: FSMContext,
) -> None:
    try:
        if (
            callback_data.action
            == superadmin_tournaments_kb.SuperadminTournamentCalendarAction.CANCEL
        ):
            await state.clear()
            await callback.answer()
            if callback.message is not None:
                await send_superadmin_panel(
                    callback.message,
                    superadmin_telegram_id=callback.from_user.id,
                    text=panel_text.SUPERADMIN_PANEL_WELCOME,
                )
            return
        if (
            callback_data.action
            == superadmin_tournaments_kb.SuperadminTournamentCalendarAction.BACK_HUB
        ):
            await _edit_tournament_hub(callback, state)
            return
        if callback_data.action in {
            superadmin_tournaments_kb.SuperadminTournamentCalendarAction.MONTH,
            superadmin_tournaments_kb.SuperadminTournamentCalendarAction.BACK_MONTH,
        }:
            await _edit_calendar_month(
                callback,
                state=state,
                year=callback_data.year,
                month=callback_data.month,
            )
            return
        if callback_data.action in {
            superadmin_tournaments_kb.SuperadminTournamentCalendarAction.WEEK,
            superadmin_tournaments_kb.SuperadminTournamentCalendarAction.BACK_WEEK,
        }:
            await _edit_calendar_week(
                callback,
                year=callback_data.year,
                month=callback_data.month,
                row=callback_data.row,
            )
            return
        if callback_data.action == superadmin_tournaments_kb.SuperadminTournamentCalendarAction.DAY:
            await _edit_calendar_day(callback, callback_data)
            return
        if (
            callback_data.action
            == superadmin_tournaments_kb.SuperadminTournamentCalendarAction.CREATE_TYPE
        ):
            preview = await tournament_planning_service.get_calendar_create_preview(
                callback.from_user.id,
                tournament_date=date.fromisoformat(callback_data.day),
                tournament_type_id=callback_data.tournament_type_id,
            )
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=tournament_fmt.superadmin_calendar_create_preview(preview),
                    reply_markup=(
                        superadmin_tournaments_kb.calendar_create_preview_keyboard(
                            year=callback_data.year,
                            month=callback_data.month,
                            row=callback_data.row,
                            day=callback_data.day,
                            tournament_type_id=callback_data.tournament_type_id,
                        )
                    ),
                )
            return
        if (
            callback_data.action
            == superadmin_tournaments_kb.SuperadminTournamentCalendarAction.CREATE_CONFIRM
        ):
            await tournament_planning_service.create_calendar_tournament(
                callback.from_user.id,
                tournament_date=date.fromisoformat(callback_data.day),
                tournament_type_id=callback_data.tournament_type_id,
            )
            await _edit_calendar_week(
                callback,
                year=callback_data.year,
                month=callback_data.month,
                row=callback_data.row,
                answer_text=text.CALENDAR_TOURNAMENT_CREATED,
            )
            return
        if (
            callback_data.action
            == superadmin_tournaments_kb.SuperadminTournamentCalendarAction.AUTOFILL_PREVIEW
        ):
            preview = await tournament_planning_service.get_calendar_autofill_preview(
                callback.from_user.id,
                year=callback_data.year,
                month=callback_data.month,
                row_number=callback_data.row,
            )
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=tournament_fmt.superadmin_calendar_autofill_preview(preview),
                    reply_markup=(
                        superadmin_tournaments_kb.calendar_simple_confirmation_keyboard(
                            confirm_action=(
                                superadmin_tournaments_kb.SuperadminTournamentCalendarAction.AUTOFILL_CONFIRM
                            ),
                            year=callback_data.year,
                            month=callback_data.month,
                            row=callback_data.row,
                        )
                    ),
                )
            return
        if (
            callback_data.action
            == superadmin_tournaments_kb.SuperadminTournamentCalendarAction.AUTOFILL_CONFIRM
        ):
            await tournament_planning_service.create_calendar_autofill_week(
                callback.from_user.id,
                year=callback_data.year,
                month=callback_data.month,
                row_number=callback_data.row,
            )
            await _edit_calendar_week(
                callback,
                year=callback_data.year,
                month=callback_data.month,
                row=callback_data.row,
                answer_text=text.CALENDAR_WEEK_CREATED,
            )
            return
        if (
            callback_data.action
            == superadmin_tournaments_kb.SuperadminTournamentCalendarAction.APPROVE_PREVIEW
        ):
            preview = await tournament_planning_service.get_week_approval_preview(
                callback.from_user.id,
                year=callback_data.year,
                month=callback_data.month,
                row_number=callback_data.row,
            )
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=tournament_fmt.superadmin_calendar_approval_preview(preview),
                    reply_markup=(
                        superadmin_tournaments_kb.calendar_simple_confirmation_keyboard(
                            confirm_action=(
                                superadmin_tournaments_kb.SuperadminTournamentCalendarAction.APPROVE_CONFIRM
                            ),
                            year=callback_data.year,
                            month=callback_data.month,
                            row=callback_data.row,
                        )
                    ),
                )
            return
        if (
            callback_data.action
            == superadmin_tournaments_kb.SuperadminTournamentCalendarAction.APPROVE_CONFIRM
        ):
            await tournament_planning_service.approve_calendar_week(
                callback.from_user.id,
                year=callback_data.year,
                month=callback_data.month,
                row_number=callback_data.row,
            )
            await _edit_calendar_week(
                callback,
                year=callback_data.year,
                month=callback_data.month,
                row=callback_data.row,
                answer_text=text.CALENDAR_WEEK_APPROVED,
            )
            return
        if (
            callback_data.action
            == superadmin_tournaments_kb.SuperadminTournamentCalendarAction.CHANGE_TYPE
        ):
            await _edit_calendar_type_selection(callback, callback_data)
            return
        if (
            callback_data.action
            == superadmin_tournaments_kb.SuperadminTournamentCalendarAction.CHANGE_CONFIRM
        ):
            preview = await tournament_planning_service.get_type_change_preview(
                callback.from_user.id,
                tournament_id=callback_data.tournament_id,
                new_tournament_type_id=callback_data.tournament_type_id,
            )
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=tournament_fmt.superadmin_calendar_type_change_preview(preview),
                    reply_markup=(
                        superadmin_tournaments_kb.calendar_simple_confirmation_keyboard(
                            confirm_action=(
                                superadmin_tournaments_kb.SuperadminTournamentCalendarAction.CHANGE_APPLY
                            ),
                            year=callback_data.year,
                            month=callback_data.month,
                            row=callback_data.row,
                            tournament_id=callback_data.tournament_id,
                            tournament_type_id=callback_data.tournament_type_id,
                        )
                    ),
                )
            return
        if (
            callback_data.action
            == superadmin_tournaments_kb.SuperadminTournamentCalendarAction.CHANGE_APPLY
        ):
            await tournament_planning_service.change_calendar_tournament_type(
                callback.from_user.id,
                tournament_id=callback_data.tournament_id,
                new_tournament_type_id=callback_data.tournament_type_id,
            )
            await _edit_calendar_week(
                callback,
                year=callback_data.year,
                month=callback_data.month,
                row=callback_data.row,
                answer_text=text.CALENDAR_TYPE_CHANGED,
            )
            return
        if (
            callback_data.action
            == superadmin_tournaments_kb.SuperadminTournamentCalendarAction.DELETE_PREVIEW
        ):
            preview = await tournament_planning_service.get_calendar_delete_preview(
                callback.from_user.id,
                tournament_id=callback_data.tournament_id,
            )
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=tournament_fmt.superadmin_calendar_delete_preview(preview),
                    reply_markup=(
                        superadmin_tournaments_kb.calendar_simple_confirmation_keyboard(
                            confirm_action=(
                                superadmin_tournaments_kb.SuperadminTournamentCalendarAction.DELETE_CONFIRM
                            ),
                            year=callback_data.year,
                            month=callback_data.month,
                            row=callback_data.row,
                            tournament_id=callback_data.tournament_id,
                        )
                    ),
                )
            return
        if (
            callback_data.action
            == superadmin_tournaments_kb.SuperadminTournamentCalendarAction.DELETE_CONFIRM
        ):
            _deleted, notifications = await tournament_planning_service.delete_calendar_tournament(
                callback.from_user.id,
                tournament_id=callback_data.tournament_id,
            )
            await _send_tournament_cancellation_notifications(callback, notifications)
            await _edit_calendar_week(
                callback,
                year=callback_data.year,
                month=callback_data.month,
                row=callback_data.row,
                answer_text=text.CALENDAR_TOURNAMENT_DELETED,
            )
            return
    except AdminAccessDeniedError:
        await state.clear()
        await callback.answer(panel_text.INSUFFICIENT_RIGHTS, show_alert=True)
        return
    except CalendarTournamentDateAlreadyExistsError:
        await callback.answer(text.CALENDAR_DATE_BUSY, show_alert=True)
        return
    except (
        CalendarDefaultTournamentTypeNotFoundError,
        CalendarTournamentTypeNotFoundError,
        CalendarWeeklyPlanIntegrityError,
    ):
        await callback.answer(text.CALENDAR_UNAVAILABLE, show_alert=True)
        return
    except CalendarWeekNotEmptyError:
        await callback.answer(text.CALENDAR_WEEK_NOT_EMPTY, show_alert=True)
        return
    except CalendarNoUnapprovedTournamentsError:
        await callback.answer(text.CALENDAR_NO_APPROVAL_TARGETS, show_alert=True)
        return
    except (CalendarTournamentNotEditableError, CalendarTournamentNotFoundError):
        await callback.answer(text.CALENDAR_TOURNAMENT_NOT_EDITABLE, show_alert=True)
        return


@router.callback_query(superadmin_tournaments_kb.SuperadminOpenTournamentCallback.filter())
async def select_open_tournament_action(
    callback: CallbackQuery,
    callback_data: superadmin_tournaments_kb.SuperadminOpenTournamentCallback,
    state: FSMContext,
) -> None:
    try:
        if (
            callback_data.action
            == superadmin_tournaments_kb.SuperadminOpenTournamentAction.BACK_TO_HUB
        ):
            hub = await tournament_planning_service.get_superadmin_tournament_hub(
                callback.from_user.id
            )
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=text.TOURNAMENT_HUB_TITLE,
                    reply_markup=superadmin_tournaments_kb.tournament_hub_keyboard(
                        hub.open_tournaments_count
                    ),
                )
            return

        if callback_data.action == superadmin_tournaments_kb.SuperadminOpenTournamentAction.PAGE:
            await _edit_open_tournament_list(callback, page=callback_data.page)
            return

        if (
            callback_data.action
            == superadmin_tournaments_kb.SuperadminOpenTournamentAction.BACK_TO_LIST
        ):
            await _edit_open_tournament_list(callback, page=callback_data.page)
            return

        if callback_data.action == superadmin_tournaments_kb.SuperadminOpenTournamentAction.OPEN:
            await _edit_open_tournament_card(
                callback,
                tournament_id=callback_data.tournament_id,
                page=callback_data.page,
            )
            return

        if (
            callback_data.action
            == superadmin_tournaments_kb.SuperadminOpenTournamentAction.DELETE_PLAYER_LIST
        ):
            await _edit_open_tournament_delete_player_list(
                callback,
                tournament_id=callback_data.tournament_id,
                page=callback_data.page,
            )
            return

        if (
            callback_data.action
            == superadmin_tournaments_kb.SuperadminOpenTournamentAction.DELETE_PLAYER_PREVIEW
        ):
            await _edit_open_tournament_delete_player_confirmation(
                callback,
                tournament_id=callback_data.tournament_id,
                player_id=callback_data.player_id,
                page=callback_data.page,
            )
            return

        if (
            callback_data.action
            == superadmin_tournaments_kb.SuperadminOpenTournamentAction.DELETE_PLAYER_CONFIRM
        ):
            await tournament_participant_service.delete_player_from_open_tournament(
                superadmin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
                player_id=callback_data.player_id,
            )
            await _edit_open_tournament_card(
                callback,
                tournament_id=callback_data.tournament_id,
                page=callback_data.page,
                answer_text=text.OPEN_TOURNAMENT_PLAYER_DELETED,
            )
            return

        if callback_data.action == superadmin_tournaments_kb.SuperadminOpenTournamentAction.CANCEL:
            await state.clear()
            await callback.answer()
            if callback.message is not None:
                await send_superadmin_panel(
                    callback.message,
                    superadmin_telegram_id=callback.from_user.id,
                    text=panel_text.SUPERADMIN_PANEL_WELCOME,
                )
            return

        await callback.answer()
        if callback.message is not None:
            from app.bot.telegram.handlers.superadmin import (
                tournament_close as superadmin_close_handlers,
            )

            await superadmin_close_handlers.open_close_tournament_card_from_tournament_hub(
                callback=callback,
                state=state,
                tournament_id=callback_data.tournament_id,
                page=callback_data.page,
            )
    except AdminAccessDeniedError:
        await state.clear()
        await callback.answer(panel_text.INSUFFICIENT_RIGHTS, show_alert=True)
    except (FutureTournamentCannotBeClosedError, ResultTournamentNotFoundError):
        await callback.answer(text.OPEN_TOURNAMENTS_EMPTY, show_alert=True)
    except ResultUserNotFoundError:
        await callback.answer(text.OPEN_TOURNAMENT_PLAYER_STALE, show_alert=True)
    except ResultPlayerRewardConflictError:
        await callback.answer(text.OPEN_TOURNAMENT_DELETE_REWARD_CONFLICT, show_alert=True)


async def _edit_open_tournament_list(callback: CallbackQuery, *, page: int) -> None:
    page_view = await tournament_planning_service.list_open_tournaments_for_superadmin(
        callback.from_user.id,
        page=page,
    )
    await callback.answer()
    if callback.message is not None:
        await edit_message_if_changed(
            callback.message,
            text=tournament_fmt.superadmin_open_list(page_view),
            reply_markup=superadmin_tournaments_kb.open_tournament_list_keyboard(page_view),
        )


async def _edit_open_tournament_card(
    callback: CallbackQuery,
    *,
    tournament_id: int,
    page: int,
    answer_text: str | None = None,
) -> None:
    readiness = await result_service.get_close_readiness(
        superadmin_telegram_id=callback.from_user.id,
        tournament_id=tournament_id,
    )
    if answer_text is None:
        await callback.answer()
    else:
        await callback.answer(answer_text)
    if callback.message is not None:
        await edit_message_if_changed(
            callback.message,
            text=tournament_fmt.superadmin_open_card(readiness),
            reply_markup=superadmin_tournaments_kb.open_tournament_card_keyboard(
                tournament_id=tournament_id,
                page=page,
            ),
        )


async def _edit_tournament_hub(callback: CallbackQuery, state: FSMContext) -> None:
    hub = await tournament_planning_service.get_superadmin_tournament_hub(callback.from_user.id)
    await state.clear()
    await callback.answer()
    if callback.message is not None:
        await edit_message_if_changed(
            callback.message,
            text=text.TOURNAMENT_HUB_TITLE,
            reply_markup=superadmin_tournaments_kb.tournament_hub_keyboard(
                hub.open_tournaments_count
            ),
        )


async def _edit_calendar_month(
    callback: CallbackQuery,
    *,
    state: FSMContext,
    year: int | None = None,
    month: int | None = None,
) -> None:
    view = await tournament_planning_service.get_calendar_month(
        callback.from_user.id,
        year=year or None,
        month=month or None,
    )
    await state.clear()
    await callback.answer()
    if callback.message is not None:
        await edit_message_if_changed(
            callback.message,
            text=tournament_fmt.superadmin_calendar_month(view),
            reply_markup=superadmin_tournaments_kb.calendar_month_keyboard(view),
            parse_mode="Markdown",
        )


async def _edit_calendar_week(
    callback: CallbackQuery,
    *,
    year: int,
    month: int,
    row: int,
    answer_text: str | None = None,
) -> None:
    view = await tournament_planning_service.get_calendar_week(
        callback.from_user.id,
        year=year,
        month=month,
        row_number=row,
    )
    if answer_text is None:
        await callback.answer()
    else:
        await callback.answer(answer_text)
    if callback.message is not None:
        await edit_message_if_changed(
            callback.message,
            text=tournament_fmt.superadmin_calendar_week(view),
            reply_markup=superadmin_tournaments_kb.calendar_week_keyboard(view),
        )


async def _edit_calendar_day(
    callback: CallbackQuery,
    callback_data: superadmin_tournaments_kb.SuperadminTournamentCalendarCallback,
) -> None:
    week = await tournament_planning_service.get_calendar_week(
        callback.from_user.id,
        year=callback_data.year,
        month=callback_data.month,
        row_number=callback_data.row,
    )
    day = next((item for item in week.days if item.date.isoformat() == callback_data.day), None)
    if day is None:
        await callback.answer(text.CALENDAR_UNAVAILABLE, show_alert=True)
        return
    await callback.answer()
    if callback.message is None:
        return
    if day.tournament is None:
        options = await tournament_planning_service.list_calendar_tournament_type_options(
            callback.from_user.id
        )
        await edit_message_if_changed(
            callback.message,
            text="Выбери тип турнира:",
            reply_markup=superadmin_tournaments_kb.calendar_type_keyboard(
                options=options,
                action=superadmin_tournaments_kb.SuperadminTournamentCalendarAction.CREATE_TYPE,
                year=callback_data.year,
                month=callback_data.month,
                row=callback_data.row,
                day=callback_data.day,
            ),
        )
        return
    await edit_message_if_changed(
        callback.message,
        text=tournament_fmt.superadmin_calendar_tournament_card(day),
        reply_markup=superadmin_tournaments_kb.calendar_occupied_tournament_keyboard(
            day,
            year=callback_data.year,
            month=callback_data.month,
            row=callback_data.row,
        ),
    )


async def _edit_calendar_type_selection(
    callback: CallbackQuery,
    callback_data: superadmin_tournaments_kb.SuperadminTournamentCalendarCallback,
) -> None:
    options = await tournament_planning_service.list_calendar_tournament_type_options(
        callback.from_user.id
    )
    await callback.answer()
    if callback.message is not None:
        await edit_message_if_changed(
            callback.message,
            text="Выбери новый тип турнира:",
            reply_markup=superadmin_tournaments_kb.calendar_type_keyboard(
                options=options,
                action=superadmin_tournaments_kb.SuperadminTournamentCalendarAction.CHANGE_CONFIRM,
                year=callback_data.year,
                month=callback_data.month,
                row=callback_data.row,
                tournament_id=callback_data.tournament_id,
            ),
        )


async def _send_tournament_cancellation_notifications(
    callback: CallbackQuery,
    notifications: tuple[object, ...],
) -> None:
    for notification in notifications:
        try:
            await callback.bot.send_message(
                chat_id=notification.telegram_id,
                text=text.CALENDAR_TOURNAMENT_CANCELLED_USER.format(
                    tournament=tournament_fmt.label(notification.tournament)
                ),
            )
        except TelegramAPIError:
            logger.exception("Failed to send tournament cancellation notification")


async def _edit_open_tournament_delete_player_list(
    callback: CallbackQuery,
    *,
    tournament_id: int,
    page: int,
) -> None:
    readiness = await result_service.get_close_readiness(
        superadmin_telegram_id=callback.from_user.id,
        tournament_id=tournament_id,
    )
    players = await tournament_participant_service.list_open_tournament_players_for_delete(
        superadmin_telegram_id=callback.from_user.id,
        tournament_id=tournament_id,
        page=0,
        page_size=1000,
    )
    await callback.answer()
    if callback.message is not None:
        await edit_message_if_changed(
            callback.message,
            text=tournament_fmt.superadmin_open_player_list(players, readiness.tournament),
            reply_markup=superadmin_tournaments_kb.open_tournament_player_delete_list_keyboard(
                tournament_id=tournament_id,
                page=players,
                tournament_page=page,
            ),
        )


async def _edit_open_tournament_delete_player_confirmation(
    callback: CallbackQuery,
    *,
    tournament_id: int,
    player_id: int,
    page: int,
) -> None:
    preview = await tournament_participant_service.get_open_tournament_player_delete_preview(
        superadmin_telegram_id=callback.from_user.id,
        tournament_id=tournament_id,
        player_id=player_id,
    )
    await callback.answer()
    if callback.message is not None:
        await edit_message_if_changed(
            callback.message,
            text=tournament_fmt.superadmin_open_delete_confirmation(preview),
            reply_markup=(
                superadmin_tournaments_kb.open_tournament_player_delete_confirmation_keyboard(
                    tournament_id=tournament_id,
                    player_id=player_id,
                    page=page,
                )
            ),
        )
