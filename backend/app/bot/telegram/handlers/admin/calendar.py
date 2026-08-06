# ruff: noqa: F403,F405
from aiogram import Router

from app.bot.telegram.handlers.admin.common import *  # noqa: F403

router = Router(name="admin.calendar")


@router.message(F.text == keyboards.ADMIN_PANEL_EXIT)
async def exit_admin_panel(message: Message) -> None:
    if message.from_user is None:
        return

    try:
        admin_panel = await user_service.get_admin_panel_for_admin(message.from_user.id)
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
        await user_service.require_superadmin(message.from_user.id)
    except AdminAccessDeniedError:
        await message.answer(texts.admin.INSUFFICIENT_RIGHTS)
        return

    await message.answer(
        texts.admin.ADMIN_CALENDAR_PROMPT,
        reply_markup=keyboards.admin_calendar_keyboard(),
    )


@router.callback_query(keyboards.AdminCalendarCallback.filter())
async def select_admin_calendar_section(
    callback: CallbackQuery,
    callback_data: keyboards.AdminCalendarCallback,
    state: FSMContext,
) -> None:
    try:
        await user_service.require_superadmin(callback.from_user.id)
    except AdminAccessDeniedError:
        await callback.answer(texts.admin.INSUFFICIENT_RIGHTS, show_alert=True)
        return

    await _delete_callback_message(callback)

    if callback_data.action == keyboards.AdminCalendarAction.CANCEL:
        await state.clear()
        await callback.answer(texts.admin.ADMIN_CALENDAR_CANCELLED)
        if callback.message is not None:
            await callback.message.answer(texts.admin.ADMIN_CALENDAR_CANCELLED)
        return

    if callback_data.action == keyboards.AdminCalendarAction.SEASONS:
        try:
            proposal = await season_service.create_season_proposal(callback.from_user.id)
        except AdminAccessDeniedError:
            await state.clear()
            await callback.answer(texts.admin.INSUFFICIENT_RIGHTS, show_alert=True)
            return
        except (SeasonScoringConfigAmbiguousError, SeasonScoringConfigNotFoundError):
            await callback.answer(texts.admin.ADMIN_CALENDAR_EMPTY_SEASONS)
            if callback.message is not None:
                await callback.message.answer(texts.admin.ADMIN_CALENDAR_EMPTY_SEASONS)
            return

        await state.clear()
        await callback.answer()
        if callback.message is not None:
            await callback.message.answer(
                format_season_proposal(proposal),
                reply_markup=keyboards.season_open_confirmation_keyboard(proposal.id),
            )
        return

    try:
        prompt = await calendar_service.create_weekly_tournament_prompt()
    except CalendarTournamentDateAlreadyExistsError:
        await callback.answer(texts.admin.ADMIN_CALENDAR_TOURNAMENT_DATE_EXISTS)
        if callback.message is not None:
            await callback.message.answer(texts.admin.ADMIN_CALENDAR_TOURNAMENT_DATE_EXISTS)
        return
    except (
        CalendarDefaultTournamentTypeNotFoundError,
        CalendarWeeklyPendingConflictError,
        CalendarWeeklyPromptIntegrityError,
    ):
        await callback.answer(texts.admin.CALENDAR_PROMPT_NOT_FOUND, show_alert=True)
        return

    await state.clear()
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(
            format_admin_calendar_prompt(prompt),
            reply_markup=keyboards.manual_tournaments_prompt_keyboard(prompt),
        )
