import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.telegram.formatters import tournaments as tournament_fmt
from app.bot.telegram.handlers.admin.calendar import send_planning_state_messages
from app.bot.telegram.handlers.superadmin.navigation import send_superadmin_panel
from app.bot.telegram.keyboards import labels
from app.bot.telegram.keyboards.superadmin import tournaments as superadmin_tournaments_kb
from app.bot.telegram.message_edit import edit_message_if_changed
from app.bot.telegram.texts.superadmin import panel as panel_text
from app.bot.telegram.texts.superadmin import tournaments as text
from app.services.access_policy import AdminAccessDeniedError
from app.services.result_service import (
    FutureTournamentCannotBeClosedError,
    ResultTournamentNotFoundError,
    result_service,
)
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
        await _edit_open_tournament_list(callback, page=0)
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
            == superadmin_tournaments_kb.SuperadminOpenTournamentAction.DELETE_PLAYER
        ):
            readiness = await result_service.get_close_readiness(
                superadmin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
            )
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=text.OPEN_TOURNAMENT_DELETE_PLAYER_PLACEHOLDER,
                    reply_markup=superadmin_tournaments_kb.open_tournament_card_keyboard(
                        tournament_id=readiness.tournament.id,
                        page=callback_data.page,
                    ),
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
) -> None:
    readiness = await result_service.get_close_readiness(
        superadmin_telegram_id=callback.from_user.id,
        tournament_id=tournament_id,
    )
    await callback.answer()
    if callback.message is not None:
        await edit_message_if_changed(
            callback.message,
            text=tournament_fmt.superadmin_open_card(readiness),
            reply_markup=superadmin_tournaments_kb.open_tournament_card_keyboard(
                tournament_id=tournament_id,
                page=page,
            ),
        )
