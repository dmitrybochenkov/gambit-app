import logging

from aiogram import Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from app.bot.telegram.formatters import publications as publication_fmt
from app.bot.telegram.handlers.admin.shared import resolve_admin_actor_user_id
from app.bot.telegram.keyboards.admin import calendar as admin_calendar_kb
from app.bot.telegram.message_edit import edit_message_if_changed
from app.bot.telegram.texts.admin import calendar as calendar_text
from app.bot.telegram.texts.superadmin import panel as superadmin_panel_text
from app.db.models.enums import TournamentPublicationDestination, TournamentPublicationType
from app.services.access_policy import AdminAccessDeniedError
from app.services.tournament_publication_service import (
    TournamentPublicationAlreadyPublishedError,
    TournamentPublicationNoDestinationsError,
    tournament_publication_service,
)

logger = logging.getLogger(__name__)

router = Router(name="admin.schedule")


@router.callback_query(admin_calendar_kb.CalendarPlanCallback.filter())
async def review_calendar_plan(
    callback: CallbackQuery,
    callback_data: admin_calendar_kb.CalendarPlanCallback,
    state: FSMContext,
) -> None:
    try:
        if callback_data.action == admin_calendar_kb.CalendarPlanAction.PUBLISH_PREVIEW:
            preview = await tournament_publication_service.get_schedule_publication_preview(
                await resolve_admin_actor_user_id(callback.from_user.id)
            )
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=publication_fmt.schedule_publication_preview(preview),
                    reply_markup=admin_calendar_kb.schedule_publication_preview_keyboard(),
                    parse_mode="HTML",
                )
            return

        if callback_data.action == admin_calendar_kb.CalendarPlanAction.PUBLISH_CONFIRM:
            preview = await tournament_publication_service.get_schedule_publication_preview(
                await resolve_admin_actor_user_id(callback.from_user.id)
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

        await state.clear()
        await callback.answer(calendar_text.CALENDAR_PLAN_CANCELLED)
    except AdminAccessDeniedError:
        await callback.answer(superadmin_panel_text.INSUFFICIENT_RIGHTS, show_alert=True)
    except TournamentPublicationNoDestinationsError:
        await callback.answer("Не настроены получатели публикации.", show_alert=True)
    except TournamentPublicationAlreadyPublishedError:
        await callback.answer("Расписание уже опубликовано.", show_alert=True)


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
                    parse_mode="HTML",
                )
                if first_message_id is None:
                    first_message_id = message.message_id
        except TelegramAPIError:
            logger.exception("Failed to publish tournament schedule")
            failed.append(destination.destination_type)
            continue
        await tournament_publication_service.record_publication_success(
            actor_user_id=await resolve_admin_actor_user_id(callback.from_user.id),
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
