# ruff: noqa: F403,F405
from aiogram import Router

from app.bot.telegram.handlers.admin.common import *  # noqa: F403

router = Router(name="admin.schedule")


@router.callback_query(keyboards.CalendarPromptCallback.filter())
async def review_calendar_prompt(
    callback: CallbackQuery,
    callback_data: keyboards.CalendarPromptCallback,
    state: FSMContext,
) -> None:
    try:
        await user_service.require_superadmin(callback.from_user.id)
        if callback_data.action == keyboards.CalendarPromptAction.EDIT:
            await state.clear()
            prompt = await calendar_service.get_tournament_prompt(
                callback.from_user.id,
                callback_data.prompt_id,
            )
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer(
                    texts.admin.ADMIN_CALENDAR_EDIT_MENU,
                    reply_markup=keyboards.tournament_prompt_day_edit_keyboard(prompt),
                )
            await callback.answer()
            return

        if callback_data.action == keyboards.CalendarPromptAction.BACK:
            await state.clear()
            prompt = await calendar_service.get_tournament_prompt(
                callback.from_user.id,
                callback_data.prompt_id,
            )
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer(
                    format_admin_calendar_prompt(prompt),
                    reply_markup=keyboards.manual_tournaments_prompt_keyboard(prompt),
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
        await callback.answer(texts.admin.INSUFFICIENT_RIGHTS, show_alert=True)
        return
    except CalendarPromptNotFoundError:
        await callback.answer(texts.admin.CALENDAR_PROMPT_STALE, show_alert=True)
        return
    except CalendarPromptAlreadyResolvedError:
        await callback.answer(
            texts.admin.CALENDAR_PROMPT_ALREADY_RESOLVED,
            show_alert=True,
        )
        return
    except CalendarTournamentDateAlreadyExistsError:
        await callback.answer(texts.admin.ADMIN_CALENDAR_TOURNAMENT_DATE_EXISTS)
        if callback.message is not None:
            await callback.message.answer(texts.admin.ADMIN_CALENDAR_TOURNAMENT_DATE_EXISTS)
        return
    except CalendarWeeklyPromptEmptyError:
        await callback.answer(texts.admin.CALENDAR_WEEKLY_PROMPT_EMPTY)
        if callback.message is not None:
            await callback.message.answer(texts.admin.CALENDAR_WEEKLY_PROMPT_EMPTY)
        return
    except (
        CalendarDefaultTournamentTypeNotFoundError,
        CalendarWeeklyPendingConflictError,
        CalendarWeeklyPromptIntegrityError,
    ):
        await callback.answer(texts.admin.CALENDAR_PROMPT_NOT_FOUND, show_alert=True)
        return

    if callback_data.action == keyboards.CalendarPromptAction.CONFIRM:
        result_text = (
            texts.admin.ADMIN_CALENDAR_TOURNAMENTS_CREATED
            if resolved_prompt.kind == AdminPromptKind.TOURNAMENTS_PROPOSAL
            else texts.admin.CALENDAR_PROMPT_CONFIRMED
        )
        await callback.answer(result_text)
        if callback.message is not None:
            await _delete_callback_message(callback)
            await callback.message.answer(format_created_tournaments_prompt(resolved_prompt))
            if resolved_prompt.kind == AdminPromptKind.TOURNAMENTS_PROPOSAL:
                schedule = await calendar_service.get_created_weekly_schedule(
                    callback.from_user.id, callback_data.prompt_id
                )
                for schedule_message in format_public_weekly_schedule(schedule):
                    await callback.message.answer(schedule_message)
        return
    elif callback_data.action == keyboards.CalendarPromptAction.CANCEL:
        result_text = texts.admin.CALENDAR_PROMPT_CANCELLED
        await state.clear()
        await callback.answer(result_text)
        if callback.message is not None:
            await _delete_callback_message(callback)
            await callback.message.answer(result_text)
        return


@router.callback_query(keyboards.TournamentPromptDayEditCallback.filter())
async def select_tournament_prompt_day(
    callback: CallbackQuery,
    callback_data: keyboards.TournamentPromptDayEditCallback,
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
        await callback.answer(texts.admin.INSUFFICIENT_RIGHTS, show_alert=True)
        return
    except (
        ValueError,
        CalendarPromptInvalidPayloadError,
        CalendarPromptNotFoundError,
        CalendarPromptAlreadyResolvedError,
        CalendarTournamentDateNotInPromptError,
    ):
        await callback.answer(texts.admin.CALENDAR_PROMPT_STALE, show_alert=True)
        return

    await state.clear()
    await callback.answer()
    if callback.message is not None:
        await _delete_callback_message(callback)
        await callback.message.answer(
            texts.admin.admin_calendar_tournament_type_prompt(edit_view.tournament_date),
            reply_markup=keyboards.tournament_type_edit_keyboard(edit_view),
        )


@router.callback_query(keyboards.TournamentTypeEditCallback.filter())
async def select_tournament_type(
    callback: CallbackQuery,
    callback_data: keyboards.TournamentTypeEditCallback,
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
        await callback.answer(texts.admin.INSUFFICIENT_RIGHTS, show_alert=True)
        return
    except (CalendarPromptNotFoundError, CalendarPromptAlreadyResolvedError):
        await callback.answer(
            texts.admin.CALENDAR_PROMPT_ALREADY_RESOLVED,
            show_alert=True,
        )
        return
    except (
        ValueError,
        CalendarPromptInvalidPayloadError,
        CalendarTournamentDateNotInPromptError,
    ):
        await callback.answer(texts.admin.CALENDAR_PROMPT_STALE, show_alert=True)
        return

    await state.clear()
    await callback.answer(texts.admin.CALENDAR_PROMPT_CONFIRMED)
    if callback.message is not None:
        await _delete_callback_message(callback)
        await callback.message.answer(
            format_admin_calendar_prompt(prompt),
            reply_markup=keyboards.manual_tournaments_prompt_keyboard(prompt),
        )
