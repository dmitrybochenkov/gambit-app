import logging
from datetime import date

from aiogram import Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from app.bot.telegram.formatters import publications as publication_fmt
from app.bot.telegram.formatters import schedules as schedule_fmt
from app.bot.telegram.handlers.admin.shared import (
    delete_callback_message as _delete_callback_message,
)
from app.bot.telegram.keyboards.admin import calendar as admin_calendar_kb
from app.bot.telegram.keyboards.admin import schedule as admin_schedule_kb
from app.bot.telegram.message_edit import edit_message_if_changed
from app.bot.telegram.texts.admin import calendar as calendar_text
from app.bot.telegram.texts.admin import schedule as schedule_text
from app.bot.telegram.texts.superadmin import panel as superadmin_panel_text
from app.db.models.enums import TournamentPublicationDestination, TournamentPublicationType
from app.services.access_policy import AdminAccessDeniedError
from app.services.dto.schedules import WeeklyTournamentPlanView
from app.services.tournament_planning_service import (
    CalendarDefaultTournamentTypeNotFoundError,
    CalendarPlanStaleError,
    CalendarTournamentDateAlreadyExistsError,
    CalendarTournamentDateNotInPlanError,
    CalendarTournamentTypeNotFoundError,
    CalendarWeeklyPlanEmptyError,
    CalendarWeeklyPlanIntegrityError,
    WeeklyTournamentPlan,
    tournament_planning_service,
)
from app.services.tournament_publication_service import (
    TournamentPublicationAlreadyPublishedError,
    TournamentPublicationNoDestinationsError,
    tournament_publication_service,
)
from app.services.tournament_schedule_service import tournament_schedule_service

logger = logging.getLogger(__name__)


router = Router(name="admin.schedule")

FSM_PLAN_KEY = "weekly_tournament_plan"


@router.callback_query(admin_calendar_kb.CalendarPlanCallback.filter())
async def review_calendar_plan(
    callback: CallbackQuery,
    callback_data: admin_calendar_kb.CalendarPlanCallback,
    state: FSMContext,
) -> None:
    try:
        if callback_data.action == admin_calendar_kb.CalendarPlanAction.PUBLISH_PREVIEW:
            preview = await tournament_publication_service.get_schedule_publication_preview(
                callback.from_user.id
            )
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=publication_fmt.schedule_publication_preview(preview),
                    reply_markup=admin_calendar_kb.schedule_publication_preview_keyboard(),
                )
            return

        if callback_data.action == admin_calendar_kb.CalendarPlanAction.PUBLISH_CONFIRM:
            preview = await tournament_publication_service.get_schedule_publication_preview(
                callback.from_user.id
            )
            summary = await _publish_schedule(callback, preview)
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=publication_fmt.schedule_publication_summary(summary),
                    reply_markup=(
                        admin_calendar_kb.schedule_publication_preview_keyboard()
                        if summary.has_failures
                        else None
                    ),
                )
            return

        if callback_data.action == admin_calendar_kb.CalendarPlanAction.EDIT:
            plan_view = await _plan_view_from_state_or_service(
                callback.from_user.id,
                state,
                store_if_missing=True,
            )
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer(
                    calendar_text.ADMIN_CALENDAR_EDIT_MENU,
                    reply_markup=admin_schedule_kb.tournament_plan_day_edit_keyboard(plan_view),
                )
            await callback.answer()
            return

        if callback_data.action == admin_calendar_kb.CalendarPlanAction.BACK:
            plan_view = await _plan_view_from_state(callback.from_user.id, state)
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer(
                    schedule_fmt.plan_preview(plan_view),
                    reply_markup=admin_schedule_kb.manual_tournaments_plan_keyboard(plan_view),
                )
            await callback.answer()
            return

        if callback_data.action == admin_calendar_kb.CalendarPlanAction.CANCEL:
            await state.clear()
            await callback.answer(calendar_text.CALENDAR_PLAN_CANCELLED)
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer(calendar_text.CALENDAR_PLAN_CANCELLED)
            return

        plan = await _plan_from_state_or_service(callback.from_user.id, state)
        created_plan = await tournament_planning_service.create_weekly_schedule(
            actor_telegram_id=callback.from_user.id,
            plan=plan,
        )
        schedule = await tournament_schedule_service.get_created_weekly_schedule(
            callback.from_user.id,
            plan,
        )
    except AdminAccessDeniedError:
        await callback.answer(superadmin_panel_text.INSUFFICIENT_RIGHTS, show_alert=True)
        return
    except TournamentPublicationNoDestinationsError:
        await callback.answer("Не настроены получатели публикации.", show_alert=True)
        return
    except TournamentPublicationAlreadyPublishedError:
        await callback.answer("Расписание уже опубликовано.", show_alert=True)
        return
    except CalendarPlanStaleError:
        await state.clear()
        await callback.answer(calendar_text.CALENDAR_PLAN_STALE, show_alert=True)
        return
    except CalendarTournamentDateAlreadyExistsError:
        await callback.answer(calendar_text.ADMIN_CALENDAR_TOURNAMENT_DATE_EXISTS)
        if callback.message is not None:
            await callback.message.answer(calendar_text.ADMIN_CALENDAR_TOURNAMENT_DATE_EXISTS)
        return
    except CalendarWeeklyPlanEmptyError:
        await callback.answer(calendar_text.CALENDAR_WEEKLY_PROMPT_EMPTY)
        if callback.message is not None:
            await callback.message.answer(calendar_text.CALENDAR_WEEKLY_PROMPT_EMPTY)
        return
    except (
        CalendarDefaultTournamentTypeNotFoundError,
        CalendarTournamentTypeNotFoundError,
        CalendarWeeklyPlanIntegrityError,
    ):
        await callback.answer(calendar_text.CALENDAR_PLAN_NOT_FOUND, show_alert=True)
        return

    await state.clear()
    await callback.answer(calendar_text.ADMIN_CALENDAR_TOURNAMENTS_CREATED)
    if callback.message is not None:
        await _delete_callback_message(callback)
        await callback.message.answer(schedule_fmt.created_plan(created_plan))
        for schedule_message in schedule_fmt.public_weekly(schedule):
            await callback.message.answer(schedule_message)
        await callback.message.answer(
            "Расписание готово к публикации.",
            reply_markup=admin_calendar_kb.schedule_publication_action_keyboard(),
        )


@router.callback_query(admin_schedule_kb.TournamentPlanDayEditCallback.filter())
async def select_tournament_plan_day(
    callback: CallbackQuery,
    callback_data: admin_schedule_kb.TournamentPlanDayEditCallback,
    state: FSMContext,
) -> None:
    try:
        plan = _plan_from_state(await state.get_data())
        edit_view = await tournament_planning_service.get_day_edit_options(
            actor_telegram_id=callback.from_user.id,
            plan=plan,
            tournament_date=date.fromisoformat(callback_data.tournament_date),
        )
    except AdminAccessDeniedError:
        await state.clear()
        await callback.answer(superadmin_panel_text.INSUFFICIENT_RIGHTS, show_alert=True)
        return
    except (
        ValueError,
        CalendarPlanStaleError,
        CalendarTournamentDateNotInPlanError,
        CalendarWeeklyPlanIntegrityError,
    ):
        await callback.answer(calendar_text.CALENDAR_PLAN_STALE, show_alert=True)
        return

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
        plan = _plan_from_state(await state.get_data())
        plan_view = await tournament_planning_service.update_plan_day_type(
            actor_telegram_id=callback.from_user.id,
            plan=plan,
            tournament_date=date.fromisoformat(callback_data.tournament_date),
            tournament_type_id=callback_data.tournament_type_id,
        )
        updated_plan = plan.with_tournament_type(
            date.fromisoformat(callback_data.tournament_date),
            callback_data.tournament_type_id,
        )
        await state.update_data(**{FSM_PLAN_KEY: updated_plan.to_fsm()})
    except AdminAccessDeniedError:
        await callback.answer(superadmin_panel_text.INSUFFICIENT_RIGHTS, show_alert=True)
        return
    except (
        ValueError,
        CalendarPlanStaleError,
        CalendarTournamentDateNotInPlanError,
        CalendarTournamentTypeNotFoundError,
        CalendarWeeklyPlanIntegrityError,
    ):
        await callback.answer(calendar_text.CALENDAR_PLAN_STALE, show_alert=True)
        return

    await callback.answer(calendar_text.CALENDAR_PLAN_CONFIRMED)
    if callback.message is not None:
        await _delete_callback_message(callback)
        await callback.message.answer(
            schedule_fmt.plan_preview(plan_view),
            reply_markup=admin_schedule_kb.manual_tournaments_plan_keyboard(plan_view),
        )


@router.callback_query(admin_schedule_kb.TournamentPlanDayDeleteCallback.filter())
async def delete_tournament_plan_day(
    callback: CallbackQuery,
    callback_data: admin_schedule_kb.TournamentPlanDayDeleteCallback,
    state: FSMContext,
) -> None:
    try:
        plan = _plan_from_state(await state.get_data())
        plan_view = await tournament_planning_service.remove_plan_day(
            actor_telegram_id=callback.from_user.id,
            plan=plan,
            tournament_date=date.fromisoformat(callback_data.tournament_date),
        )
        updated_plan = plan.without_date(date.fromisoformat(callback_data.tournament_date))
        await state.update_data(**{FSM_PLAN_KEY: updated_plan.to_fsm()})
    except AdminAccessDeniedError:
        await callback.answer(superadmin_panel_text.INSUFFICIENT_RIGHTS, show_alert=True)
        return
    except CalendarWeeklyPlanEmptyError:
        await callback.answer(calendar_text.CALENDAR_WEEKLY_PROMPT_EMPTY)
        return
    except (
        ValueError,
        CalendarPlanStaleError,
        CalendarTournamentDateNotInPlanError,
        CalendarWeeklyPlanIntegrityError,
    ):
        await callback.answer(calendar_text.CALENDAR_PLAN_STALE, show_alert=True)
        return

    await callback.answer(calendar_text.CALENDAR_PLAN_CONFIRMED)
    if callback.message is not None:
        await _delete_callback_message(callback)
        await callback.message.answer(
            schedule_fmt.plan_preview(plan_view),
            reply_markup=admin_schedule_kb.manual_tournaments_plan_keyboard(plan_view),
        )


async def _publish_schedule(callback: CallbackQuery, preview: object) -> object:
    messages = publication_fmt.schedule_publication_messages(preview)
    sent: list[str] = []
    failed: list[str] = []
    already_published: list[str] = []
    for destination in preview.destinations:
        if destination.already_published:
            already_published.append(destination.destination_type)
            continue
        try:
            first_message_id: int | None = None
            for text in messages:
                message = await callback.bot.send_message(
                    chat_id=destination.chat_id,
                    text=text,
                )
                if first_message_id is None:
                    first_message_id = message.message_id
        except TelegramAPIError:
            logger.exception("Failed to publish tournament schedule")
            failed.append(destination.destination_type)
            continue
        await tournament_publication_service.record_publication_success(
            superadmin_telegram_id=callback.from_user.id,
            tournament_id=None,
            publication_type=TournamentPublicationType.SCHEDULE,
            destination_type=TournamentPublicationDestination(destination.destination_type),
            destination_chat_id=destination.chat_id,
            content_hash=preview.content_hash,
            telegram_message_id=first_message_id,
        )
        sent.append(destination.destination_type)
    return tournament_publication_service.delivery_summary(
        sent=sent,
        failed=failed,
        already_published=already_published,
    )


async def store_plan_in_state(state: FSMContext, plan_view: WeeklyTournamentPlanView) -> None:
    await state.update_data(
        **{
            FSM_PLAN_KEY: [
                {
                    "date": item.date.isoformat(),
                    "tournament_type_id": item.tournament_type.id,
                }
                for item in plan_view.tournaments
            ]
        }
    )


def _plan_from_state(data: dict[str, object]) -> WeeklyTournamentPlan:
    return WeeklyTournamentPlan.from_fsm(data.get(FSM_PLAN_KEY))


async def _plan_from_state_or_service(
    actor_telegram_id: int,
    state: FSMContext,
) -> WeeklyTournamentPlan:
    data = await state.get_data()
    if FSM_PLAN_KEY in data:
        return _plan_from_state(data)
    plan_view = await tournament_planning_service.build_next_week_plan(actor_telegram_id)
    return _plan_from_view(plan_view)


async def _plan_view_from_state_or_service(
    actor_telegram_id: int,
    state: FSMContext,
    *,
    store_if_missing: bool,
) -> WeeklyTournamentPlanView:
    data = await state.get_data()
    if FSM_PLAN_KEY in data:
        return await _plan_view_from_state(actor_telegram_id, state)
    plan_view = await tournament_planning_service.build_next_week_plan(actor_telegram_id)
    if store_if_missing:
        await store_plan_in_state(state, plan_view)
    return plan_view


async def _plan_view_from_state(
    actor_telegram_id: int,
    state: FSMContext,
) -> WeeklyTournamentPlanView:
    return await tournament_planning_service.get_plan_view(
        actor_telegram_id,
        _plan_from_state(await state.get_data()),
    )


def _plan_from_view(plan_view: WeeklyTournamentPlanView) -> WeeklyTournamentPlan:
    return WeeklyTournamentPlan.create(
        target_dates=tuple(item.date for item in plan_view.tournaments),
        tournament_type_ids=tuple(item.tournament_type.id for item in plan_view.tournaments),
    )
