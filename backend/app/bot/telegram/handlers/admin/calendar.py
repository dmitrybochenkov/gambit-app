import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.telegram.formatters import schedules as schedule_fmt
from app.bot.telegram.formatters import seasons as season_fmt
from app.bot.telegram.handlers.admin.shared import (
    delete_callback_message as _delete_callback_message,
)
from app.bot.telegram.keyboards import labels
from app.bot.telegram.keyboards.admin import calendar as admin_calendar_kb
from app.bot.telegram.keyboards.admin import schedule as admin_schedule_kb
from app.bot.telegram.keyboards.superadmin import seasons as superadmin_seasons_kb
from app.bot.telegram.keyboards.user import menu as user_menu_kb
from app.bot.telegram.texts.admin import calendar as calendar_text
from app.bot.telegram.texts.admin import panel as panel_text
from app.bot.telegram.texts.superadmin import panel as superadmin_panel_text
from app.services.access_policy import AdminAccessDeniedError
from app.services.season_service import (
    SeasonScoringConfigAmbiguousError,
    SeasonScoringConfigNotFoundError,
    season_service,
)
from app.services.tournament_proposal_service import (
    CalendarDefaultTournamentTypeNotFoundError,
    CalendarTournamentDateAlreadyExistsError,
    CalendarWeeklyPendingConflictError,
    CalendarWeeklyPromptIntegrityError,
    tournament_proposal_service,
)
from app.services.user_access_service import user_access_service

logger = logging.getLogger(__name__)


router = Router(name="admin.calendar")


@router.message(F.text == labels.ADMIN_PANEL_EXIT)
async def exit_admin_panel(message: Message) -> None:
    if message.from_user is None:
        return

    try:
        admin_panel = await user_access_service.get_admin_panel_for_admin(message.from_user.id)
    except AdminAccessDeniedError:
        await message.answer(panel_text.ACCESS_DENIED)
        return

    await message.answer(
        panel_text.ADMIN_PANEL_EXITED,
        reply_markup=user_menu_kb.main_keyboard_for_player(admin_panel.admin),
    )


@router.message(F.text == labels.ADMIN_PANEL_CALENDAR)
async def open_admin_calendar(message: Message) -> None:
    if message.from_user is None:
        return

    try:
        await user_access_service.require_superadmin(message.from_user.id)
    except AdminAccessDeniedError:
        await message.answer(superadmin_panel_text.INSUFFICIENT_RIGHTS)
        return

    await message.answer(
        calendar_text.ADMIN_CALENDAR_PROMPT,
        reply_markup=admin_calendar_kb.admin_calendar_keyboard(),
    )


@router.callback_query(admin_calendar_kb.AdminCalendarCallback.filter())
async def select_admin_calendar_section(
    callback: CallbackQuery,
    callback_data: admin_calendar_kb.AdminCalendarCallback,
    state: FSMContext,
) -> None:
    try:
        await user_access_service.require_superadmin(callback.from_user.id)
    except AdminAccessDeniedError:
        await callback.answer(superadmin_panel_text.INSUFFICIENT_RIGHTS, show_alert=True)
        return

    await _delete_callback_message(callback)

    if callback_data.action == admin_calendar_kb.AdminCalendarAction.CANCEL:
        await state.clear()
        await callback.answer(calendar_text.ADMIN_CALENDAR_CANCELLED)
        if callback.message is not None:
            await callback.message.answer(calendar_text.ADMIN_CALENDAR_CANCELLED)
        return

    if callback_data.action == admin_calendar_kb.AdminCalendarAction.SEASONS:
        try:
            proposal = await season_service.create_season_proposal(callback.from_user.id)
        except AdminAccessDeniedError:
            await state.clear()
            await callback.answer(superadmin_panel_text.INSUFFICIENT_RIGHTS, show_alert=True)
            return
        except (SeasonScoringConfigAmbiguousError, SeasonScoringConfigNotFoundError):
            await callback.answer(calendar_text.ADMIN_CALENDAR_EMPTY_SEASONS)
            if callback.message is not None:
                await callback.message.answer(calendar_text.ADMIN_CALENDAR_EMPTY_SEASONS)
            return

        await state.clear()
        await callback.answer()
        if callback.message is not None:
            await callback.message.answer(
                season_fmt.proposal(proposal),
                reply_markup=superadmin_seasons_kb.season_open_confirmation_keyboard(proposal.id),
            )
        return

    try:
        prompt = await tournament_proposal_service.create_weekly_tournament_prompt(
            callback.from_user.id
        )
    except CalendarTournamentDateAlreadyExistsError:
        await callback.answer(calendar_text.ADMIN_CALENDAR_TOURNAMENT_DATE_EXISTS)
        if callback.message is not None:
            await callback.message.answer(calendar_text.ADMIN_CALENDAR_TOURNAMENT_DATE_EXISTS)
        return
    except (
        CalendarDefaultTournamentTypeNotFoundError,
        CalendarWeeklyPendingConflictError,
        CalendarWeeklyPromptIntegrityError,
    ):
        await callback.answer(calendar_text.CALENDAR_PROMPT_NOT_FOUND, show_alert=True)
        return

    await state.clear()
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(
            schedule_fmt.prompt(prompt),
            reply_markup=admin_schedule_kb.manual_tournaments_prompt_keyboard(prompt),
        )
