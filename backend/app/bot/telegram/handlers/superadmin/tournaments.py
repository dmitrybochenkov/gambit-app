import logging
from datetime import date, timedelta

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.telegram.formatters import tournaments as tournament_fmt
from app.bot.telegram.handlers.admin.shared import resolve_admin_actor_user_id
from app.bot.telegram.handlers.superadmin.navigation import send_superadmin_panel
from app.bot.telegram.keyboards import labels
from app.bot.telegram.keyboards.superadmin import tournaments as superadmin_tournaments_kb
from app.bot.telegram.message_edit import edit_message_if_changed, edit_reply_markup_if_changed
from app.bot.telegram.states import WeeklyAutofillEditorStates, WeeklyTemplateEditorStates
from app.bot.telegram.texts.superadmin import panel as panel_text
from app.bot.telegram.texts.superadmin import tournaments as text
from app.services.access_policy import AdminAccessDeniedError
from app.services.dto.tournaments import (
    TournamentCalendarDraftCommand,
    TournamentCalendarDraftItem,
)
from app.services.result_service import (
    FutureTournamentCannotBeClosedError,
    ResultPlayerRewardConflictError,
    ResultTournamentNotFoundError,
    ResultUserNotFoundError,
    result_service,
)
from app.services.tournament_participant_service import tournament_participant_service
from app.services.tournament_planning_service import (
    CalendarAutofillDraftInvalidError,
    CalendarDefaultTournamentTypeNotFoundError,
    CalendarNoUnapprovedTournamentsError,
    CalendarTournamentDateAlreadyExistsError,
    CalendarTournamentNotEditableError,
    CalendarTournamentNotFoundError,
    CalendarTournamentTypeNotFoundError,
    CalendarWeeklyPlanIntegrityError,
    CalendarWeekNotEmptyError,
    WeeklyTemplateInvalidError,
    WeeklyTemplateTournamentTypeNotAllowedError,
    tournament_planning_service,
)

logger = logging.getLogger(__name__)

router = Router(name="superadmin.tournaments")

_TEMPLATE_DRAFT_KEY = "weekly_template_draft"
_TEMPLATE_CONTEXT_KEY = "weekly_template_context"
_AUTOFILL_DRAFT_KEY = "weekly_autofill_draft"
_AUTOFILL_CONTEXT_KEY = "weekly_autofill_context"


@router.message(F.text == labels.SUPERADMIN_PANEL_TOURNAMENTS)
async def open_tournament_hub(message: Message) -> None:
    if message.from_user is None:
        return

    try:
        hub = await tournament_planning_service.get_superadmin_tournament_hub(
            await resolve_admin_actor_user_id(message.from_user.id)
        )
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

        await tournament_planning_service.get_superadmin_tournament_hub(
            await resolve_admin_actor_user_id(callback.from_user.id)
        )
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
                await resolve_admin_actor_user_id(callback.from_user.id),
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
                await resolve_admin_actor_user_id(callback.from_user.id),
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
                await resolve_admin_actor_user_id(callback.from_user.id),
                year=callback_data.year,
                month=callback_data.month,
                row_number=callback_data.row,
            )
            draft = {
                (preview.week_start + timedelta(days=offset)).isoformat(): None
                for offset in range(7)
            }
            for item in preview.tournaments:
                draft[item.tournament_date.isoformat()] = item.tournament_type.id
            await state.set_state(WeeklyAutofillEditorStates.editing)
            await state.update_data(
                **{
                    _AUTOFILL_DRAFT_KEY: draft,
                    _AUTOFILL_CONTEXT_KEY: {
                        "year": callback_data.year,
                        "month": callback_data.month,
                        "row": callback_data.row,
                    },
                }
            )
            await _render_weekly_autofill_main(callback, state)
            return
        if (
            callback_data.action
            == superadmin_tournaments_kb.SuperadminTournamentCalendarAction.AUTOFILL_CONFIRM
        ):
            await callback.answer(text.WEEKLY_AUTOFILL_INVALID, show_alert=True)
            return
        if (
            callback_data.action
            == superadmin_tournaments_kb.SuperadminTournamentCalendarAction.APPROVE_PREVIEW
        ):
            preview = await tournament_planning_service.get_week_approval_preview(
                await resolve_admin_actor_user_id(callback.from_user.id),
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
                await resolve_admin_actor_user_id(callback.from_user.id),
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
                await resolve_admin_actor_user_id(callback.from_user.id),
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
                await resolve_admin_actor_user_id(callback.from_user.id),
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
                await resolve_admin_actor_user_id(callback.from_user.id),
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
                await resolve_admin_actor_user_id(callback.from_user.id),
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
    except CalendarDefaultTournamentTypeNotFoundError:
        await callback.answer(text.CALENDAR_TEMPLATE_UNAVAILABLE, show_alert=True)
        return
    except (
        CalendarAutofillDraftInvalidError,
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


@router.callback_query(superadmin_tournaments_kb.WeeklyAutofillCallback.filter())
async def edit_weekly_autofill(
    callback: CallbackQuery,
    callback_data: superadmin_tournaments_kb.WeeklyAutofillCallback,
    state: FSMContext,
) -> None:
    try:
        draft, context = await _weekly_autofill_state(state)
        _validate_weekly_autofill_callback(draft, callback_data)
        action = callback_data.action
        weekday = callback_data.weekday

        if action == superadmin_tournaments_kb.WeeklyAutofillAction.CANCEL:
            await state.clear()
            await callback.answer()
            if callback.message is not None:
                await send_superadmin_panel(
                    callback.message,
                    superadmin_telegram_id=callback.from_user.id,
                    text=panel_text.SUPERADMIN_PANEL_WELCOME,
                )
            return
        if action == superadmin_tournaments_kb.WeeklyAutofillAction.BACK_WEEK:
            await state.clear()
            await _edit_calendar_week(callback, **context)
            return
        if action == superadmin_tournaments_kb.WeeklyAutofillAction.BACK_MAIN:
            await _render_weekly_autofill_main(callback, state)
            return
        if action == superadmin_tournaments_kb.WeeklyAutofillAction.DAY:
            await _render_weekly_autofill_day(callback, state, weekday)
            return
        if action in {
            superadmin_tournaments_kb.WeeklyAutofillAction.PICK,
            superadmin_tournaments_kb.WeeklyAutofillAction.PICK_PAGE,
        }:
            await _render_weekly_autofill_options(
                callback,
                state,
                weekday,
                page=callback_data.page,
            )
            return
        if action == superadmin_tournaments_kb.WeeklyAutofillAction.SELECT:
            options = await tournament_planning_service.list_calendar_tournament_type_options(
                await resolve_admin_actor_user_id(callback.from_user.id)
            )
            if callback_data.tournament_type_id not in {option.id for option in options}:
                raise CalendarAutofillDraftInvalidError
            draft[_autofill_date_for_weekday(draft, weekday)] = callback_data.tournament_type_id
            await _store_weekly_autofill_draft(state, draft)
            await _render_weekly_autofill_main(callback, state)
            return
        if action == superadmin_tournaments_kb.WeeklyAutofillAction.REMOVE:
            draft[_autofill_date_for_weekday(draft, weekday)] = None
            await _store_weekly_autofill_draft(state, draft)
            await _render_weekly_autofill_main(callback, state)
            return
        if action == superadmin_tournaments_kb.WeeklyAutofillAction.CONFIRM:
            items = tuple(
                TournamentCalendarDraftItem(
                    tournament_date=tournament_date,
                    tournament_type_id=tournament_type_id,
                )
                for tournament_date, tournament_type_id in draft.items()
                if tournament_type_id is not None
            )
            if not items:
                await callback.answer(text.WEEKLY_AUTOFILL_EMPTY, show_alert=True)
                return
            await tournament_planning_service.create_calendar_autofill_draft(
                await resolve_admin_actor_user_id(callback.from_user.id),
                TournamentCalendarDraftCommand(
                    year=context["year"],
                    month=context["month"],
                    row_number=context["row"],
                    tournaments=items,
                ),
            )
            await state.clear()
            await _edit_calendar_week(
                callback,
                **context,
                answer_text=text.CALENDAR_WEEK_CREATED,
            )
    except AdminAccessDeniedError:
        await state.clear()
        await callback.answer(panel_text.INSUFFICIENT_RIGHTS, show_alert=True)
    except CalendarWeekNotEmptyError:
        await callback.answer(text.CALENDAR_WEEK_NOT_EMPTY, show_alert=True)
    except CalendarTournamentDateAlreadyExistsError:
        await callback.answer(text.CALENDAR_DATE_BUSY, show_alert=True)
    except (
        CalendarAutofillDraftInvalidError,
        CalendarTournamentTypeNotFoundError,
        CalendarWeeklyPlanIntegrityError,
        WeeklyTemplateInvalidError,
    ):
        await callback.answer(text.WEEKLY_AUTOFILL_INVALID, show_alert=True)


@router.callback_query(superadmin_tournaments_kb.WeeklyTemplateCallback.filter())
async def edit_weekly_template(
    callback: CallbackQuery,
    callback_data: superadmin_tournaments_kb.WeeklyTemplateCallback,
    state: FSMContext,
) -> None:
    action = callback_data.action
    try:
        if action == superadmin_tournaments_kb.WeeklyTemplateAction.OPEN:
            view = await tournament_planning_service.get_weekly_template(
                await resolve_admin_actor_user_id(callback.from_user.id)
            )
            draft = {day.weekday: [item.id for item in day.tournament_types] for day in view.days}
            await state.set_state(WeeklyTemplateEditorStates.editing)
            await state.update_data(
                **{
                    _TEMPLATE_DRAFT_KEY: draft,
                    _TEMPLATE_CONTEXT_KEY: {
                        "year": callback_data.year,
                        "month": callback_data.month,
                        "row": callback_data.row,
                    },
                }
            )
            await _render_weekly_template_main(callback, state)
            return

        draft, context = await _weekly_template_state(state)
        _validate_weekly_template_callback(draft, callback_data)
        weekday = callback_data.weekday
        if action == superadmin_tournaments_kb.WeeklyTemplateAction.CANCEL:
            await state.clear()
            await _edit_calendar_week(callback, **context)
            return
        if action == superadmin_tournaments_kb.WeeklyTemplateAction.SAVE:
            await tournament_planning_service.replace_weekly_template(
                await resolve_admin_actor_user_id(callback.from_user.id),
                tournament_type_ids_by_weekday={
                    day: tuple(type_ids) for day, type_ids in draft.items()
                },
            )
            await state.clear()
            await _edit_calendar_week(
                callback,
                **context,
                answer_text=text.WEEKLY_TEMPLATE_SAVED,
            )
            return
        if action == superadmin_tournaments_kb.WeeklyTemplateAction.BACK_MAIN:
            await _render_weekly_template_main(callback, state)
            return
        if action in {
            superadmin_tournaments_kb.WeeklyTemplateAction.DAY,
            superadmin_tournaments_kb.WeeklyTemplateAction.BACK_DAY,
        }:
            await _render_weekly_template_day(callback, state, weekday)
            return
        if action in {
            superadmin_tournaments_kb.WeeklyTemplateAction.ADD_LIST,
            superadmin_tournaments_kb.WeeklyTemplateAction.ADD_PAGE,
        }:
            await _render_weekly_template_add_options(
                callback, state, weekday, page=callback_data.page
            )
            return
        if action == superadmin_tournaments_kb.WeeklyTemplateAction.ADD:
            options = await tournament_planning_service.list_weekly_template_add_options(
                await resolve_admin_actor_user_id(callback.from_user.id),
                selected_tournament_type_ids=tuple(draft[weekday]),
            )
            if callback_data.tournament_type_id not in {item.id for item in options}:
                raise WeeklyTemplateTournamentTypeNotAllowedError
            draft[weekday].append(callback_data.tournament_type_id)
            await _store_weekly_template_draft(state, draft)
            await _render_weekly_template_day(callback, state, weekday)
            return
        if action == superadmin_tournaments_kb.WeeklyTemplateAction.CLEAR:
            draft[weekday] = []
            await _store_weekly_template_draft(state, draft)
            await _render_weekly_template_day(callback, state, weekday)
            return
        if action == superadmin_tournaments_kb.WeeklyTemplateAction.ITEM:
            await _render_weekly_template_item(callback, state, weekday, callback_data.index)
            return
        if action in {
            superadmin_tournaments_kb.WeeklyTemplateAction.UP,
            superadmin_tournaments_kb.WeeklyTemplateAction.DOWN,
            superadmin_tournaments_kb.WeeklyTemplateAction.REMOVE,
        }:
            items = draft[weekday]
            index = callback_data.index
            if index < 0 or index >= len(items):
                raise WeeklyTemplateInvalidError
            if action == superadmin_tournaments_kb.WeeklyTemplateAction.REMOVE:
                items.pop(index)
                await _store_weekly_template_draft(state, draft)
                await _render_weekly_template_day(callback, state, weekday)
                return
            target = (
                index - 1
                if action == superadmin_tournaments_kb.WeeklyTemplateAction.UP
                else index + 1
            )
            if target < 0 or target >= len(items):
                raise WeeklyTemplateInvalidError
            items[index], items[target] = items[target], items[index]
            await _store_weekly_template_draft(state, draft)
            await _render_weekly_template_item(callback, state, weekday, target)
    except AdminAccessDeniedError:
        await state.clear()
        await callback.answer(panel_text.INSUFFICIENT_RIGHTS, show_alert=True)
    except (WeeklyTemplateInvalidError, WeeklyTemplateTournamentTypeNotAllowedError):
        await callback.answer(text.WEEKLY_TEMPLATE_INVALID, show_alert=True)


@router.callback_query(superadmin_tournaments_kb.TournamentFormatCallback.filter())
async def manage_tournament_formats(
    callback: CallbackQuery,
    callback_data: superadmin_tournaments_kb.TournamentFormatCallback,
    state: FSMContext,
) -> None:
    try:
        draft, _context = await _weekly_template_state(state)
        _validate_tournament_format_callback(callback_data)
        action = callback_data.action
        if action == superadmin_tournaments_kb.TournamentFormatAction.BACK_TEMPLATE:
            await _render_weekly_template_main(callback, state)
            return
        if action in {
            superadmin_tournaments_kb.TournamentFormatAction.LIST,
            superadmin_tournaments_kb.TournamentFormatAction.PAGE,
        }:
            await _render_tournament_format_list(callback, page=callback_data.page)
            return
        if action == superadmin_tournaments_kb.TournamentFormatAction.DETAIL:
            await _render_tournament_format_detail(
                callback,
                tournament_type_id=callback_data.tournament_type_id,
                page=callback_data.page,
            )
            return
        if action == superadmin_tournaments_kb.TournamentFormatAction.ENABLE:
            await tournament_planning_service.set_tournament_format_creatable(
                await resolve_admin_actor_user_id(callback.from_user.id),
                tournament_type_id=callback_data.tournament_type_id,
                is_creatable=True,
            )
            await _render_tournament_format_detail(
                callback,
                tournament_type_id=callback_data.tournament_type_id,
                page=callback_data.page,
            )
            return
        if action == superadmin_tournaments_kb.TournamentFormatAction.DISABLE_PREVIEW:
            view = await tournament_planning_service.get_tournament_format(
                await resolve_admin_actor_user_id(callback.from_user.id),
                callback_data.tournament_type_id,
            )
            affected = set(view.affected_weekdays)
            affected.update(
                weekday
                for weekday, type_ids in draft.items()
                if callback_data.tournament_type_id in type_ids
            )
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=tournament_fmt.tournament_format_disable_confirmation(
                        view.tournament_format,
                        tuple(sorted(affected)),
                    ),
                    reply_markup=(
                        superadmin_tournaments_kb.tournament_format_disable_confirmation_keyboard(
                            tournament_type_id=callback_data.tournament_type_id,
                            page=callback_data.page,
                        )
                    ),
                )
            return
        if action == superadmin_tournaments_kb.TournamentFormatAction.DISABLE_CONFIRM:
            await tournament_planning_service.set_tournament_format_creatable(
                await resolve_admin_actor_user_id(callback.from_user.id),
                tournament_type_id=callback_data.tournament_type_id,
                is_creatable=False,
            )
            updated_draft = {
                weekday: [
                    type_id for type_id in type_ids if type_id != callback_data.tournament_type_id
                ]
                for weekday, type_ids in draft.items()
            }
            await _store_weekly_template_draft(state, updated_draft)
            await _render_tournament_format_detail(
                callback,
                tournament_type_id=callback_data.tournament_type_id,
                page=callback_data.page,
            )
    except AdminAccessDeniedError:
        await callback.answer(panel_text.INSUFFICIENT_RIGHTS, show_alert=True)
    except (CalendarTournamentTypeNotFoundError, WeeklyTemplateInvalidError):
        await callback.answer(text.TOURNAMENT_FORMAT_INVALID, show_alert=True)


@router.callback_query(
    superadmin_tournaments_kb.SuperadminTournamentCalendarFormatCallback.filter()
)
async def select_tournament_calendar_format_action(
    callback: CallbackQuery,
    callback_data: superadmin_tournaments_kb.SuperadminTournamentCalendarFormatCallback,
    state: FSMContext,
) -> None:
    try:
        if (
            callback_data.action
            == superadmin_tournaments_kb.SuperadminTournamentCalendarFormatAction.BACK_LIST
        ):
            view = await tournament_planning_service.get_calendar_month(
                await resolve_admin_actor_user_id(callback.from_user.id),
                year=callback_data.year,
                month=callback_data.month,
            )
            await callback.answer()
            if callback.message is not None:
                await edit_reply_markup_if_changed(
                    callback.message,
                    reply_markup=superadmin_tournaments_kb.calendar_month_keyboard(view),
                )
            return
        if (
            callback_data.action
            == superadmin_tournaments_kb.SuperadminTournamentCalendarFormatAction.BACK_CALENDAR
        ):
            await _edit_calendar_month(
                callback,
                state=state,
                year=callback_data.year,
                month=callback_data.month,
            )
            return
        if callback_data.action in {
            superadmin_tournaments_kb.SuperadminTournamentCalendarFormatAction.LIST,
            superadmin_tournaments_kb.SuperadminTournamentCalendarFormatAction.PAGE,
        }:
            view = await tournament_planning_service.get_calendar_month(
                await resolve_admin_actor_user_id(callback.from_user.id),
                year=callback_data.year,
                month=callback_data.month,
            )
            await callback.answer()
            if callback.message is not None:
                await edit_reply_markup_if_changed(
                    callback.message,
                    reply_markup=superadmin_tournaments_kb.calendar_format_help_keyboard(
                        view,
                        page=callback_data.page,
                    ),
                )
            return
        if (
            callback_data.action
            == superadmin_tournaments_kb.SuperadminTournamentCalendarFormatAction.DETAIL
        ):
            detail = await tournament_planning_service.get_calendar_format_detail(
                await resolve_admin_actor_user_id(callback.from_user.id),
                year=callback_data.year,
                month=callback_data.month,
                tournament_type_id=callback_data.tournament_type_id,
            )
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=tournament_fmt.superadmin_calendar_format_detail(detail),
                    reply_markup=superadmin_tournaments_kb.calendar_format_detail_keyboard(
                        year=callback_data.year,
                        month=callback_data.month,
                    ),
                )
            return
    except AdminAccessDeniedError:
        await state.clear()
        await callback.answer(panel_text.INSUFFICIENT_RIGHTS, show_alert=True)
        return
    except CalendarTournamentTypeNotFoundError:
        await callback.answer(text.CALENDAR_UNAVAILABLE, show_alert=True)
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
                await resolve_admin_actor_user_id(callback.from_user.id)
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
                actor_user_id=await resolve_admin_actor_user_id(callback.from_user.id),
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
        await resolve_admin_actor_user_id(callback.from_user.id),
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
        actor_user_id=await resolve_admin_actor_user_id(callback.from_user.id),
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
    hub = await tournament_planning_service.get_superadmin_tournament_hub(
        await resolve_admin_actor_user_id(callback.from_user.id)
    )
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
        await resolve_admin_actor_user_id(callback.from_user.id),
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
        await resolve_admin_actor_user_id(callback.from_user.id),
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
        await resolve_admin_actor_user_id(callback.from_user.id),
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
            await resolve_admin_actor_user_id(callback.from_user.id)
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


async def _weekly_template_state(
    state: FSMContext,
) -> tuple[dict[int, list[int]], dict[str, int]]:
    data = await state.get_data()
    raw_draft = data.get(_TEMPLATE_DRAFT_KEY)
    raw_context = data.get(_TEMPLATE_CONTEXT_KEY)
    if not isinstance(raw_draft, dict) or not isinstance(raw_context, dict):
        raise WeeklyTemplateInvalidError
    draft = {
        weekday: list(raw_draft.get(weekday, raw_draft.get(str(weekday), [])))
        for weekday in range(7)
    }
    try:
        context = {
            "year": int(raw_context["year"]),
            "month": int(raw_context["month"]),
            "row": int(raw_context["row"]),
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise WeeklyTemplateInvalidError from exc
    return draft, context


def _validate_tournament_format_callback(
    callback_data: superadmin_tournaments_kb.TournamentFormatCallback,
) -> None:
    if callback_data.page < 0:
        raise WeeklyTemplateInvalidError
    if (
        callback_data.action
        in {
            superadmin_tournaments_kb.TournamentFormatAction.DETAIL,
            superadmin_tournaments_kb.TournamentFormatAction.ENABLE,
            superadmin_tournaments_kb.TournamentFormatAction.DISABLE_PREVIEW,
            superadmin_tournaments_kb.TournamentFormatAction.DISABLE_CONFIRM,
        }
        and callback_data.tournament_type_id <= 0
    ):
        raise WeeklyTemplateInvalidError


async def _render_tournament_format_list(callback: CallbackQuery, *, page: int) -> None:
    formats = await tournament_planning_service.list_tournament_formats(
        await resolve_admin_actor_user_id(callback.from_user.id)
    )
    await callback.answer()
    if callback.message is not None:
        await edit_message_if_changed(
            callback.message,
            text=tournament_fmt.tournament_format_list(),
            reply_markup=superadmin_tournaments_kb.tournament_format_list_keyboard(
                formats=formats,
                page=page,
            ),
        )


async def _render_tournament_format_detail(
    callback: CallbackQuery,
    *,
    tournament_type_id: int,
    page: int,
) -> None:
    view = await tournament_planning_service.get_tournament_format(
        await resolve_admin_actor_user_id(callback.from_user.id),
        tournament_type_id,
    )
    await callback.answer()
    if callback.message is not None:
        await edit_message_if_changed(
            callback.message,
            text=tournament_fmt.tournament_format_detail(view.tournament_format),
            reply_markup=superadmin_tournaments_kb.tournament_format_detail_keyboard(
                tournament_type_id=tournament_type_id,
                is_creatable=view.tournament_format.is_creatable,
                page=page,
            ),
        )


async def _weekly_autofill_state(
    state: FSMContext,
) -> tuple[dict[date, int | None], dict[str, int]]:
    data = await state.get_data()
    raw_draft = data.get(_AUTOFILL_DRAFT_KEY)
    raw_context = data.get(_AUTOFILL_CONTEXT_KEY)
    if not isinstance(raw_draft, dict) or not isinstance(raw_context, dict):
        raise CalendarAutofillDraftInvalidError
    try:
        draft = {
            date.fromisoformat(str(raw_date)): (
                None if tournament_type_id is None else int(tournament_type_id)
            )
            for raw_date, tournament_type_id in raw_draft.items()
        }
        context = {
            "year": int(raw_context["year"]),
            "month": int(raw_context["month"]),
            "row": int(raw_context["row"]),
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise CalendarAutofillDraftInvalidError from exc
    if context["year"] < 1 or context["month"] not in range(1, 13) or context["row"] < 1:
        raise CalendarAutofillDraftInvalidError
    if len(draft) != 7 or tuple(draft) != tuple(sorted(draft)):
        raise CalendarAutofillDraftInvalidError
    week_start = next(iter(draft))
    if week_start.weekday() != 0 or tuple(draft) != tuple(
        week_start + timedelta(days=offset) for offset in range(7)
    ):
        raise CalendarAutofillDraftInvalidError
    return draft, context


def _validate_weekly_autofill_callback(
    draft: dict[date, int | None],
    callback_data: superadmin_tournaments_kb.WeeklyAutofillCallback,
) -> None:
    action = callback_data.action
    weekday_actions = {
        superadmin_tournaments_kb.WeeklyAutofillAction.DAY,
        superadmin_tournaments_kb.WeeklyAutofillAction.PICK,
        superadmin_tournaments_kb.WeeklyAutofillAction.PICK_PAGE,
        superadmin_tournaments_kb.WeeklyAutofillAction.SELECT,
        superadmin_tournaments_kb.WeeklyAutofillAction.REMOVE,
    }
    if action in weekday_actions and callback_data.weekday not in range(7):
        raise CalendarAutofillDraftInvalidError
    if (
        action == superadmin_tournaments_kb.WeeklyAutofillAction.PICK_PAGE
        and callback_data.page < 0
    ):
        raise CalendarAutofillDraftInvalidError
    if (
        action == superadmin_tournaments_kb.WeeklyAutofillAction.SELECT
        and callback_data.tournament_type_id <= 0
    ):
        raise CalendarAutofillDraftInvalidError
    if action == superadmin_tournaments_kb.WeeklyAutofillAction.REMOVE:
        tournament_date = _autofill_date_for_weekday(draft, callback_data.weekday)
        if draft[tournament_date] is None:
            raise CalendarAutofillDraftInvalidError


def _autofill_date_for_weekday(draft: dict[date, int | None], weekday: int) -> date:
    try:
        return next(item for item in draft if item.weekday() == weekday)
    except StopIteration as exc:
        raise CalendarAutofillDraftInvalidError from exc


async def _store_weekly_autofill_draft(
    state: FSMContext,
    draft: dict[date, int | None],
) -> None:
    await state.update_data(
        **{
            _AUTOFILL_DRAFT_KEY: {
                tournament_date.isoformat(): tournament_type_id
                for tournament_date, tournament_type_id in draft.items()
            }
        }
    )


async def _weekly_autofill_render_data(
    callback: CallbackQuery,
    state: FSMContext,
) -> tuple[dict[date, object | None], dict[str, int]]:
    draft, context = await _weekly_autofill_state(state)
    catalog = await _weekly_template_catalog(
        await resolve_admin_actor_user_id(callback.from_user.id)
    )
    try:
        rendered = {
            tournament_date: (None if tournament_type_id is None else catalog[tournament_type_id])
            for tournament_date, tournament_type_id in draft.items()
        }
    except KeyError as exc:
        raise CalendarAutofillDraftInvalidError from exc
    return rendered, context


async def _render_weekly_autofill_main(callback: CallbackQuery, state: FSMContext) -> None:
    draft, _context = await _weekly_autofill_render_data(callback, state)
    dates = tuple(draft)
    await callback.answer()
    if callback.message is not None:
        await edit_message_if_changed(
            callback.message,
            text=tournament_fmt.weekly_autofill_summary(
                week_start=dates[0],
                week_end=dates[-1],
                draft=draft,
            ),
            reply_markup=superadmin_tournaments_kb.weekly_autofill_main_keyboard(),
        )


async def _render_weekly_autofill_day(
    callback: CallbackQuery,
    state: FSMContext,
    weekday: int,
) -> None:
    draft, _context = await _weekly_autofill_render_data(callback, state)
    tournament_date = _autofill_date_for_weekday(draft, weekday)
    tournament_type = draft[tournament_date]
    await callback.answer()
    if callback.message is not None:
        await edit_message_if_changed(
            callback.message,
            text=tournament_fmt.weekly_autofill_day(tournament_date, tournament_type),
            reply_markup=superadmin_tournaments_kb.weekly_autofill_day_keyboard(
                weekday=weekday,
                has_tournament=tournament_type is not None,
            ),
        )


async def _render_weekly_autofill_options(
    callback: CallbackQuery,
    state: FSMContext,
    weekday: int,
    *,
    page: int,
) -> None:
    draft, _context = await _weekly_autofill_state(state)
    _autofill_date_for_weekday(draft, weekday)
    options = await tournament_planning_service.list_calendar_tournament_type_options(
        await resolve_admin_actor_user_id(callback.from_user.id)
    )
    await callback.answer()
    if callback.message is not None:
        await edit_message_if_changed(
            callback.message,
            text="Выбери формат:",
            reply_markup=superadmin_tournaments_kb.weekly_autofill_type_keyboard(
                weekday=weekday,
                options=options,
                page=page,
            ),
        )


def _validate_weekly_template_callback(
    draft: dict[int, list[int]],
    callback_data: superadmin_tournaments_kb.WeeklyTemplateCallback,
) -> None:
    action = callback_data.action
    weekday_actions = {
        superadmin_tournaments_kb.WeeklyTemplateAction.DAY,
        superadmin_tournaments_kb.WeeklyTemplateAction.ADD_LIST,
        superadmin_tournaments_kb.WeeklyTemplateAction.ADD_PAGE,
        superadmin_tournaments_kb.WeeklyTemplateAction.ADD,
        superadmin_tournaments_kb.WeeklyTemplateAction.ITEM,
        superadmin_tournaments_kb.WeeklyTemplateAction.UP,
        superadmin_tournaments_kb.WeeklyTemplateAction.DOWN,
        superadmin_tournaments_kb.WeeklyTemplateAction.REMOVE,
        superadmin_tournaments_kb.WeeklyTemplateAction.CLEAR,
        superadmin_tournaments_kb.WeeklyTemplateAction.BACK_DAY,
    }
    if action in weekday_actions and callback_data.weekday not in draft:
        raise WeeklyTemplateInvalidError

    index_actions = {
        superadmin_tournaments_kb.WeeklyTemplateAction.ITEM,
        superadmin_tournaments_kb.WeeklyTemplateAction.UP,
        superadmin_tournaments_kb.WeeklyTemplateAction.DOWN,
        superadmin_tournaments_kb.WeeklyTemplateAction.REMOVE,
    }
    if action in index_actions and not (
        0 <= callback_data.index < len(draft[callback_data.weekday])
    ):
        raise WeeklyTemplateInvalidError

    if (
        action
        in {
            superadmin_tournaments_kb.WeeklyTemplateAction.ADD_LIST,
            superadmin_tournaments_kb.WeeklyTemplateAction.ADD_PAGE,
        }
        and callback_data.page < 0
    ):
        raise WeeklyTemplateInvalidError
    if (
        action == superadmin_tournaments_kb.WeeklyTemplateAction.ADD
        and callback_data.tournament_type_id <= 0
    ):
        raise WeeklyTemplateInvalidError


async def _store_weekly_template_draft(
    state: FSMContext,
    draft: dict[int, list[int]],
) -> None:
    await state.update_data(**{_TEMPLATE_DRAFT_KEY: draft})


async def _weekly_template_catalog(actor_user_id: int) -> dict[int, object]:
    template = await tournament_planning_service.get_weekly_template(actor_user_id)
    options = await tournament_planning_service.list_weekly_template_add_options(
        actor_user_id,
        selected_tournament_type_ids=(),
    )
    return {
        item.id: item
        for item in [
            *(item for day in template.days for item in day.tournament_types),
            *options,
        ]
    }


async def _weekly_template_render_data(
    callback: CallbackQuery,
    state: FSMContext,
) -> tuple[dict[int, list[object]], dict[str, int]]:
    draft, context = await _weekly_template_state(state)
    catalog = await _weekly_template_catalog(
        await resolve_admin_actor_user_id(callback.from_user.id)
    )
    try:
        rendered = {
            weekday: [catalog[tournament_type_id] for tournament_type_id in type_ids]
            for weekday, type_ids in draft.items()
        }
    except KeyError as exc:
        raise WeeklyTemplateInvalidError from exc
    return rendered, context


async def _render_weekly_template_main(callback: CallbackQuery, state: FSMContext) -> None:
    draft, context = await _weekly_template_render_data(callback, state)
    await callback.answer()
    if callback.message is not None:
        await edit_message_if_changed(
            callback.message,
            text=tournament_fmt.weekly_template_summary(draft),
            reply_markup=superadmin_tournaments_kb.weekly_template_main_keyboard(**context),
        )


async def _render_weekly_template_day(
    callback: CallbackQuery,
    state: FSMContext,
    weekday: int,
) -> None:
    draft, _context = await _weekly_template_render_data(callback, state)
    if weekday not in draft:
        raise WeeklyTemplateInvalidError
    await callback.answer()
    if callback.message is not None:
        await edit_message_if_changed(
            callback.message,
            text=tournament_fmt.weekly_template_day(weekday, draft[weekday]),
            reply_markup=superadmin_tournaments_kb.weekly_template_day_keyboard(
                weekday=weekday,
                item_count=len(draft[weekday]),
            ),
        )


async def _render_weekly_template_item(
    callback: CallbackQuery,
    state: FSMContext,
    weekday: int,
    index: int,
) -> None:
    draft, _context = await _weekly_template_render_data(callback, state)
    if weekday not in draft or index < 0 or index >= len(draft[weekday]):
        raise WeeklyTemplateInvalidError
    await callback.answer()
    if callback.message is not None:
        await edit_message_if_changed(
            callback.message,
            text=tournament_fmt.weekly_template_item(draft[weekday][index]),
            reply_markup=superadmin_tournaments_kb.weekly_template_item_keyboard(
                weekday=weekday,
                index=index,
                item_count=len(draft[weekday]),
            ),
        )


async def _render_weekly_template_add_options(
    callback: CallbackQuery,
    state: FSMContext,
    weekday: int,
    *,
    page: int,
) -> None:
    draft, _context = await _weekly_template_state(state)
    if weekday not in draft:
        raise WeeklyTemplateInvalidError
    options = await tournament_planning_service.list_weekly_template_add_options(
        await resolve_admin_actor_user_id(callback.from_user.id),
        selected_tournament_type_ids=tuple(draft[weekday]),
    )
    await callback.answer()
    if callback.message is not None:
        await edit_message_if_changed(
            callback.message,
            text="Выбери формат:",
            reply_markup=superadmin_tournaments_kb.weekly_template_add_keyboard(
                weekday=weekday,
                options=options,
                page=page,
            ),
        )


async def _edit_calendar_type_selection(
    callback: CallbackQuery,
    callback_data: superadmin_tournaments_kb.SuperadminTournamentCalendarCallback,
) -> None:
    options = await tournament_planning_service.list_calendar_tournament_type_options(
        await resolve_admin_actor_user_id(callback.from_user.id)
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
        actor_user_id=await resolve_admin_actor_user_id(callback.from_user.id),
        tournament_id=tournament_id,
    )
    players = await tournament_participant_service.list_open_tournament_players_for_delete(
        actor_user_id=await resolve_admin_actor_user_id(callback.from_user.id),
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
        actor_user_id=await resolve_admin_actor_user_id(callback.from_user.id),
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
