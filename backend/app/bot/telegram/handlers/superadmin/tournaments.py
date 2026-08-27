import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.telegram.handlers.admin.calendar import send_planning_state_messages
from app.bot.telegram.handlers.superadmin.navigation import send_superadmin_panel
from app.bot.telegram.keyboards import labels
from app.bot.telegram.keyboards.superadmin import tournaments as superadmin_tournaments_kb
from app.bot.telegram.message_edit import edit_message_if_changed
from app.bot.telegram.texts.superadmin import panel as panel_text
from app.bot.telegram.texts.superadmin import tournaments as text
from app.services.access_policy import AdminAccessDeniedError
from app.services.tournament_planning_service import (
    CalendarDefaultTournamentTypeNotFoundError,
    CalendarWeeklyPlanIntegrityError,
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

        hub = await tournament_planning_service.get_superadmin_tournament_hub(callback.from_user.id)
    except AdminAccessDeniedError:
        await state.clear()
        await callback.answer(panel_text.INSUFFICIENT_RIGHTS, show_alert=True)
        return

    if callback_data.action == superadmin_tournaments_kb.SuperadminTournamentHubAction.CREATE:
        try:
            planning = await tournament_planning_service.inspect_next_week(callback.from_user.id)
        except (
            CalendarDefaultTournamentTypeNotFoundError,
            CalendarWeeklyPlanIntegrityError,
        ):
            await callback.answer(text.TOURNAMENT_PLANNING_UNAVAILABLE, show_alert=True)
            return

        await state.clear()
        await callback.answer()
        if callback.message is not None:
            await send_planning_state_messages(
                callback.message,
                planning,
                include_controls=True,
            )
        return

    if callback_data.action == superadmin_tournaments_kb.SuperadminTournamentHubAction.OPEN:
        await callback.answer()
        if callback.message is not None:
            await edit_message_if_changed(
                callback.message,
                text=text.OPEN_TOURNAMENTS_PLACEHOLDER,
                reply_markup=superadmin_tournaments_kb.tournament_hub_keyboard(
                    hub.open_tournaments_count
                ),
            )
        return

    await callback.answer()
    if callback.message is not None:
        await edit_message_if_changed(
            callback.message,
            text=text.CLOSED_TOURNAMENTS_PLACEHOLDER,
            reply_markup=superadmin_tournaments_kb.tournament_hub_keyboard(
                hub.open_tournaments_count
            ),
        )
