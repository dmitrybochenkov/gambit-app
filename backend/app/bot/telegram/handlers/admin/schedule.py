import logging
from datetime import date

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from app.bot.telegram.formatters import schedules as schedule_fmt
from app.bot.telegram.handlers.admin.shared import (
    delete_callback_message as _delete_callback_message,
)
from app.bot.telegram.keyboards.admin import calendar as admin_calendar_kb
from app.bot.telegram.keyboards.admin import schedule as admin_schedule_kb
from app.bot.telegram.texts.admin import calendar as calendar_text
from app.bot.telegram.texts.admin import schedule as schedule_text
from app.bot.telegram.texts.superadmin import panel as superadmin_panel_text
from app.db.models.enums import AdminPromptKind
from app.services.access_policy import AdminAccessDeniedError
from app.services.calendar_service import (
    CalendarDefaultTournamentTypeNotFoundError,
    CalendarPromptAction,
    CalendarPromptAlreadyResolvedError,
    CalendarPromptInvalidPayloadError,
    CalendarPromptNotFoundError,
    CalendarTournamentDateAlreadyExistsError,
    CalendarTournamentDateNotInPromptError,
    CalendarWeeklyPendingConflictError,
    CalendarWeeklyPromptEmptyError,
    CalendarWeeklyPromptIntegrityError,
    calendar_service,
)
from app.services.user_service import (
    user_service,
)

logger = logging.getLogger(__name__)


router = Router(name="admin.schedule")


@router.callback_query(admin_calendar_kb.CalendarPromptCallback.filter())
async def review_calendar_prompt(
    callback: CallbackQuery,
    callback_data: admin_calendar_kb.CalendarPromptCallback,
    state: FSMContext,
) -> None:
    try:
        await user_service.require_superadmin(callback.from_user.id)
        if callback_data.action == admin_calendar_kb.CalendarPromptAction.EDIT:
            await state.clear()
            prompt = await calendar_service.get_tournament_prompt(
                callback.from_user.id,
                callback_data.prompt_id,
            )
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer(
                    calendar_text.ADMIN_CALENDAR_EDIT_MENU,
                    reply_markup=admin_schedule_kb.tournament_prompt_day_edit_keyboard(prompt),
                )
            await callback.answer()
            return

        if callback_data.action == admin_calendar_kb.CalendarPromptAction.BACK:
            await state.clear()
            prompt = await calendar_service.get_tournament_prompt(
                callback.from_user.id,
                callback_data.prompt_id,
            )
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer(
                    schedule_fmt.prompt(prompt),
                    reply_markup=admin_schedule_kb.manual_tournaments_prompt_keyboard(prompt),
                )
            await callback.answer()
            return

        await state.clear()
        action = CalendarPromptAction(callback_data.action.value)
        resolved_prompt = await calendar_service.resolve_prompt(
            actor_telegram_id=callback.from_user.id,
            prompt_id=callback_data.prompt_id,
            action=action,
        )
    except AdminAccessDeniedError:
        await callback.answer(superadmin_panel_text.INSUFFICIENT_RIGHTS, show_alert=True)
        return
    except CalendarPromptNotFoundError:
        await callback.answer(calendar_text.CALENDAR_PROMPT_STALE, show_alert=True)
        return
    except CalendarPromptAlreadyResolvedError:
        await callback.answer(
            calendar_text.CALENDAR_PROMPT_ALREADY_RESOLVED,
            show_alert=True,
        )
        return
    except CalendarTournamentDateAlreadyExistsError:
        await callback.answer(calendar_text.ADMIN_CALENDAR_TOURNAMENT_DATE_EXISTS)
        if callback.message is not None:
            await callback.message.answer(calendar_text.ADMIN_CALENDAR_TOURNAMENT_DATE_EXISTS)
        return
    except CalendarWeeklyPromptEmptyError:
        await callback.answer(calendar_text.CALENDAR_WEEKLY_PROMPT_EMPTY)
        if callback.message is not None:
            await callback.message.answer(calendar_text.CALENDAR_WEEKLY_PROMPT_EMPTY)
        return
    except (
        CalendarDefaultTournamentTypeNotFoundError,
        CalendarWeeklyPendingConflictError,
        CalendarWeeklyPromptIntegrityError,
    ):
        await callback.answer(calendar_text.CALENDAR_PROMPT_NOT_FOUND, show_alert=True)
        return

    if callback_data.action == admin_calendar_kb.CalendarPromptAction.CONFIRM:
        result_text = (
            calendar_text.ADMIN_CALENDAR_TOURNAMENTS_CREATED
            if resolved_prompt.kind == AdminPromptKind.TOURNAMENTS_PROPOSAL
            else calendar_text.CALENDAR_PROMPT_CONFIRMED
        )
        await callback.answer(result_text)
        if callback.message is not None:
            await _delete_callback_message(callback)
            await callback.message.answer(schedule_fmt.created_prompt(resolved_prompt))
            if resolved_prompt.kind == AdminPromptKind.TOURNAMENTS_PROPOSAL:
                schedule = await calendar_service.get_created_weekly_schedule(
                    callback.from_user.id, callback_data.prompt_id
                )
                for schedule_message in schedule_fmt.public_weekly(schedule):
                    await callback.message.answer(schedule_message)
        return
    elif callback_data.action == admin_calendar_kb.CalendarPromptAction.CANCEL:
        result_text = calendar_text.CALENDAR_PROMPT_CANCELLED
        await state.clear()
        await callback.answer(result_text)
        if callback.message is not None:
            await _delete_callback_message(callback)
            await callback.message.answer(result_text)
        return


@router.callback_query(admin_schedule_kb.TournamentPromptDayEditCallback.filter())
async def select_tournament_prompt_day(
    callback: CallbackQuery,
    callback_data: admin_schedule_kb.TournamentPromptDayEditCallback,
    state: FSMContext,
) -> None:
    try:
        await user_service.require_superadmin(callback.from_user.id)
        edit_view = await calendar_service.get_weekly_prompt_day_edit_options(
            actor_telegram_id=callback.from_user.id,
            prompt_id=callback_data.prompt_id,
            tournament_date=date.fromisoformat(callback_data.tournament_date),
        )
    except AdminAccessDeniedError:
        await state.clear()
        await callback.answer(superadmin_panel_text.INSUFFICIENT_RIGHTS, show_alert=True)
        return
    except (
        ValueError,
        CalendarPromptInvalidPayloadError,
        CalendarPromptNotFoundError,
        CalendarPromptAlreadyResolvedError,
        CalendarTournamentDateNotInPromptError,
    ):
        await callback.answer(calendar_text.CALENDAR_PROMPT_STALE, show_alert=True)
        return

    await state.clear()
    await callback.answer()
    if callback.message is not None:
        await _delete_callback_message(callback)
        await callback.message.answer(
            schedule_text.tournament_type_prompt(edit_view.tournament_date),
            reply_markup=admin_schedule_kb.tournament_type_edit_keyboard(edit_view),
        )


@router.callback_query(admin_schedule_kb.TournamentTypeEditCallback.filter())
async def select_tournament_type(
    callback: CallbackQuery,
    callback_data: admin_schedule_kb.TournamentTypeEditCallback,
    state: FSMContext,
) -> None:
    try:
        await user_service.require_superadmin(callback.from_user.id)
        prompt = await calendar_service.update_weekly_prompt_day_type(
            actor_telegram_id=callback.from_user.id,
            prompt_id=callback_data.prompt_id,
            tournament_date=date.fromisoformat(callback_data.tournament_date),
            tournament_type_id=callback_data.tournament_type_id,
        )
    except AdminAccessDeniedError:
        await callback.answer(superadmin_panel_text.INSUFFICIENT_RIGHTS, show_alert=True)
        return
    except (CalendarPromptNotFoundError, CalendarPromptAlreadyResolvedError):
        await callback.answer(
            calendar_text.CALENDAR_PROMPT_ALREADY_RESOLVED,
            show_alert=True,
        )
        return
    except (
        ValueError,
        CalendarPromptInvalidPayloadError,
        CalendarTournamentDateNotInPromptError,
    ):
        await callback.answer(calendar_text.CALENDAR_PROMPT_STALE, show_alert=True)
        return

    await state.clear()
    await callback.answer(calendar_text.CALENDAR_PROMPT_CONFIRMED)
    if callback.message is not None:
        await _delete_callback_message(callback)
        await callback.message.answer(
            schedule_fmt.prompt(prompt),
            reply_markup=admin_schedule_kb.manual_tournaments_prompt_keyboard(prompt),
        )
