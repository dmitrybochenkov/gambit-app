import logging
from datetime import date

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InputMediaPhoto, Message

from app.bot.telegram.formatters import publications as publication_fmt
from app.bot.telegram.formatters import results as result_fmt
from app.bot.telegram.formatters import schedules as schedule_fmt
from app.bot.telegram.formatters import tournaments as tournament_fmt
from app.bot.telegram.handlers.admin.shared import (
    RESULT_SUMMARY_PARSE_MODE,
)
from app.bot.telegram.handlers.admin.shared import (
    delete_callback_message as _delete_callback_message,
)
from app.bot.telegram.handlers.admin.shared import (
    delete_message_by_id as _delete_message_by_id,
)
from app.bot.telegram.handlers.superadmin.navigation import send_superadmin_panel
from app.bot.telegram.keyboards import labels
from app.bot.telegram.keyboards.admin import results as admin_results_kb
from app.bot.telegram.keyboards.admin import schedule as admin_schedule_kb
from app.bot.telegram.keyboards.superadmin import tournament_close as superadmin_tournament_close_kb
from app.bot.telegram.keyboards.superadmin import tournaments as superadmin_tournaments_kb
from app.bot.telegram.message_edit import (
    edit_message_if_changed,
    edit_message_reply_markup_by_id_if_changed,
)
from app.bot.telegram.notifications import (
    notify_players_about_prize_stack_bonus_corrections,
    notify_players_about_prize_stack_bonuses,
)
from app.bot.telegram.states import AdminResultStates
from app.bot.telegram.texts.admin import calendar as calendar_text
from app.bot.telegram.texts.admin import results as result_text
from app.bot.telegram.texts.superadmin import panel as panel_text
from app.bot.telegram.texts.superadmin import tournament_close as text
from app.bot.telegram.texts.superadmin import tournaments as tournaments_text
from app.db.models.enums import TournamentPublicationDestination, TournamentPublicationType
from app.services.access_policy import AdminAccessDeniedError
from app.services.dto.results import ClosedTournamentCorrectionDraftView
from app.services.pagination import pagination_service
from app.services.result_fields import ResultField
from app.services.result_service import (
    ClosedTournamentCorrectionStaleError,
    FutureTournamentCannotBeClosedError,
    ResultInvalidFundError,
    ResultInvalidPlayerDataError,
    ResultPlayerAlreadyAddedError,
    ResultService,
    ResultTournamentNotFoundError,
    ResultUserNotFoundError,
    ResultValidationError,
    TournamentResultsEditingUnavailableError,
    result_service,
)
from app.services.tournament_planning_service import (
    CalendarDefaultTournamentTypeNotFoundError,
    CalendarWeeklyPlanIntegrityError,
    WeeklyPlanningStatus,
    tournament_planning_service,
)
from app.services.tournament_publication_service import (
    TournamentPublicationAlreadyPublishedError,
    TournamentPublicationNoDestinationsError,
    TournamentPublicationUnavailableError,
    tournament_publication_service,
)

logger = logging.getLogger(__name__)


router = Router(name="admin.tournament_close")

_CLOSE_RETURN_CONTEXT_OPEN_TOURNAMENTS = "superadmin_open_tournaments"


@router.message(F.text == labels.ADMIN_PANEL_CLOSE_TOURNAMENT)
async def show_close_tournament_flow(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return
    await state.clear()
    try:
        tournaments = await result_service.list_unclosed_tournaments_for_superadmin(
            message.from_user.id
        )
    except AdminAccessDeniedError:
        await message.answer(panel_text.INSUFFICIENT_RIGHTS)
        return

    ready = [item for item in tournaments if item.is_ready]
    if not ready:
        await send_superadmin_panel(
            message,
            superadmin_telegram_id=message.from_user.id,
            text=text.NO_READY_TOURNAMENTS,
        )
        return
    page = pagination_service.paginate(
        tournaments,
        page=0,
        page_size=admin_results_kb.ADMIN_RESULT_PAGE_SIZE,
    )
    await message.answer(
        result_fmt.close_tournament_list(page),
        reply_markup=superadmin_tournament_close_kb.admin_close_tournament_list_keyboard(
            page,
        ),
    )


@router.callback_query(superadmin_tournament_close_kb.AdminCloseTournamentCallback.filter())
async def select_close_tournament_action(
    callback: CallbackQuery,
    callback_data: superadmin_tournament_close_kb.AdminCloseTournamentCallback,
    state: FSMContext,
) -> None:
    try:
        if callback_data.action == superadmin_tournament_close_kb.AdminCloseTournamentAction.CANCEL:
            await state.clear()
            await callback.answer(text.ADMIN_RESULTS_CANCELLED)
            if callback.message is not None:
                await _delete_callback_message(callback)
                await send_superadmin_panel(
                    callback.message,
                    superadmin_telegram_id=callback.from_user.id,
                    text=text.ADMIN_RESULTS_CANCELLED,
                )
            return

        if callback_data.action == superadmin_tournament_close_kb.AdminCloseTournamentAction.PAGE:
            tournaments = await result_service.list_unclosed_tournaments_for_superadmin(
                callback.from_user.id
            )
            page = pagination_service.paginate(
                tournaments,
                page=callback_data.page,
                page_size=admin_results_kb.ADMIN_RESULT_PAGE_SIZE,
            )
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=result_fmt.close_tournament_list(page),
                    reply_markup=superadmin_tournament_close_kb.admin_close_tournament_list_keyboard(
                        page,
                    ),
                )
            return

        if callback_data.action == superadmin_tournament_close_kb.AdminCloseTournamentAction.BACK:
            data = await state.get_data()

            if callback.message is not None:
                await _delete_close_publication_preview(callback.message, data)

            if data.get("close_return_context") == _CLOSE_RETURN_CONTEXT_OPEN_TOURNAMENTS:
                await _edit_open_tournaments_return_context(
                    callback,
                    state,
                    page=int(data.get("close_return_page", callback_data.page)),
                )
                return

            await _edit_close_tournament_root(
                callback,
                state,
                page=callback_data.page,
            )
            return

        if callback_data.action in {
            superadmin_tournament_close_kb.AdminCloseTournamentAction.OPEN,
        }:
            await callback.answer()
            if callback.message is not None:
                await _edit_close_tournament_card(
                    callback=callback,
                    state=state,
                    tournament_id=callback_data.tournament_id,
                    page=callback_data.page,
                )
            return

        if (
            callback_data.action
            == superadmin_tournament_close_kb.AdminCloseTournamentAction.VIEW_PHOTOS
        ):
            await _send_tournament_photos(callback, callback_data.tournament_id)
            return

        if (
            callback_data.action
            == superadmin_tournament_close_kb.AdminCloseTournamentAction.CHANGE_FUND
        ):
            data = await state.get_data()

            readiness = await result_service.get_close_readiness(
                superadmin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
            )
            if not readiness.is_ready:
                raise ResultValidationError(readiness.validation_errors)

            await callback.answer()

            if callback.message is None:
                return

            await _delete_close_publication_preview(callback.message, data)

            prompt_message = await callback.message.answer(
                result_fmt.tournament_fund_prompt(readiness.tournament),
                reply_markup=superadmin_tournament_close_kb.admin_close_tournament_card_keyboard(
                    tournament_id=callback_data.tournament_id,
                    page=callback_data.page,
                ),
            )

            await _delete_callback_message(callback)

            await _set_fund_input_state(
                state,
                tournament_id=callback_data.tournament_id,
                page=callback_data.page,
                prompt_message=prompt_message,
                return_context=_close_return_context_from_state(data),
            )
            return

        if (
            callback_data.action
            == superadmin_tournament_close_kb.AdminCloseTournamentAction.CONFIRM
        ):
            data = await state.get_data()
            tournament_fund = int(data["tournament_fund"])
            results = await result_service.close_tournament(
                superadmin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
                tournament_fund=tournament_fund,
            )
            await state.clear()
            await notify_players_about_prize_stack_bonuses(
                callback.bot,
                results.newly_issued_rewards,
            )
            await callback.answer("Турнир закрыт.")
            if callback.message is not None:
                await _delete_callback_message(callback)
                await _send_calendar_planning_notification_after_close(
                    callback,
                    results.tournament.date,
                )
                await callback.message.answer("✅ Турнир закрыт.")
            return

        if (
            callback_data.action
            == superadmin_tournament_close_kb.AdminCloseTournamentAction.PUBLISH_PREVIEW
        ):
            preview = await tournament_publication_service.get_result_publication_preview(
                callback.from_user.id,
                callback_data.tournament_id,
            )
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=publication_fmt.result_publication_confirmation(preview),
                    reply_markup=superadmin_tournament_close_kb.admin_publish_results_preview_keyboard(
                        callback_data.tournament_id
                    ),
                )
            return

        if (
            callback_data.action
            == superadmin_tournament_close_kb.AdminCloseTournamentAction.PUBLISH_CONFIRM
        ):
            preview = await tournament_publication_service.get_result_publication_preview(
                callback.from_user.id,
                callback_data.tournament_id,
            )
            summary = await _publish_result_report(callback, preview)
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=publication_fmt.publication_summary(summary),
                    reply_markup=(
                        superadmin_tournament_close_kb.admin_publish_results_preview_keyboard(
                            callback_data.tournament_id
                        )
                        if summary.has_failures
                        else None
                    ),
                )
            return
    except AdminAccessDeniedError:
        await callback.answer(text.ACCESS_DENIED, show_alert=True)
        return
    except ResultInvalidFundError:
        await callback.answer(result_fmt.tournament_fund_error(), show_alert=True)
        return
    except ResultTournamentNotFoundError:
        await callback.answer(text.ADMIN_RESULTS_NOT_FOUND, show_alert=True)
        return
    except FutureTournamentCannotBeClosedError:
        await callback.answer("Будущий турнир нельзя закрыть.", show_alert=True)
        return
    except ResultValidationError as error:
        await callback.answer()
        if callback.message is not None:
            await callback.message.answer(result_fmt.close_tournament_blocked(error.errors))
        return
    except TournamentPublicationNoDestinationsError:
        await callback.answer("Не настроены получатели публикации.", show_alert=True)
        return
    except TournamentPublicationAlreadyPublishedError:
        await callback.answer("Результаты уже опубликованы.", show_alert=True)
        return
    except TournamentPublicationUnavailableError:
        await callback.answer("Результаты нельзя опубликовать.", show_alert=True)
        return

    await callback.answer(text.ADMIN_RESULTS_NOT_FOUND, show_alert=True)


@router.callback_query(superadmin_tournament_close_kb.AdminClosedCorrectionCallback.filter())
async def select_closed_correction_action(
    callback: CallbackQuery,
    callback_data: superadmin_tournament_close_kb.AdminClosedCorrectionCallback,
    state: FSMContext,
) -> None:
    try:
        if (
            callback_data.action
            == superadmin_tournament_close_kb.AdminClosedCorrectionAction.CANCEL
        ):
            await state.clear()
            await callback.answer(text.ADMIN_RESULTS_CANCELLED)
            await _return_to_superadmin_menu(callback, text.ADMIN_RESULTS_CANCELLED)
            return
        if callback_data.action == superadmin_tournament_close_kb.AdminClosedCorrectionAction.PAGE:
            await _edit_closed_correction_list(callback, page=callback_data.page)
            return
        if (
            callback_data.action
            == superadmin_tournament_close_kb.AdminClosedCorrectionAction.BACK_TO_HUB
        ):
            await _edit_tournament_hub(callback)
            return
        if callback_data.action == superadmin_tournament_close_kb.AdminClosedCorrectionAction.OPEN:
            await _edit_closed_correction_card(
                callback,
                state,
                tournament_id=callback_data.tournament_id,
                page=callback_data.page,
            )
            return
        if (
            callback_data.action
            == superadmin_tournament_close_kb.AdminClosedCorrectionAction.PLAYERS
        ):
            draft = await _closed_correction_draft(
                callback.from_user.id,
                callback_data.tournament_id,
                state,
            )
            results = await result_service.get_closed_tournament_draft_results(
                callback.from_user.id,
                draft,
            )
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=result_fmt.closed_correction_players(results),
                    reply_markup=superadmin_tournament_close_kb.admin_closed_players_menu_keyboard(
                        tournament_id=callback_data.tournament_id,
                        page=callback_data.page,
                    ),
                )
            return
        if callback_data.action == superadmin_tournament_close_kb.AdminClosedCorrectionAction.DATA:
            draft = await _closed_correction_draft(
                callback.from_user.id,
                callback_data.tournament_id,
                state,
            )
            results = await result_service.get_closed_tournament_draft_results(
                callback.from_user.id,
                draft,
            )
            page = pagination_service.paginate(
                results.players,
                page=0,
                page_size=admin_results_kb.ADMIN_RESULT_PAGE_SIZE,
            )
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=result_fmt.players_table(results, page),
                    reply_markup=superadmin_tournament_close_kb.admin_closed_result_players_keyboard(
                        results,
                        page,
                    ),
                    parse_mode=RESULT_SUMMARY_PARSE_MODE,
                )
            return
        if callback_data.action == superadmin_tournament_close_kb.AdminClosedCorrectionAction.FUND:
            draft = await _closed_correction_draft(
                callback.from_user.id,
                callback_data.tournament_id,
                state,
            )
            results = await result_service.get_closed_tournament_draft_results(
                callback.from_user.id,
                draft,
            )
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=result_fmt.closed_fund_card(results),
                    reply_markup=superadmin_tournament_close_kb.admin_closed_fund_keyboard(
                        tournament_id=callback_data.tournament_id,
                        page=callback_data.page,
                    ),
                )
            return
        if (
            callback_data.action
            == superadmin_tournament_close_kb.AdminClosedCorrectionAction.FUND_INPUT
        ):
            draft = await _closed_correction_draft(
                callback.from_user.id,
                callback_data.tournament_id,
                state,
            )
            results = await result_service.get_closed_tournament_draft_results(
                callback.from_user.id,
                draft,
            )
            await state.set_state(AdminResultStates.entering_closed_tournament_fund)
            await state.update_data(
                closed_fund_tournament_id=callback_data.tournament_id,
                closed_fund_page=callback_data.page,
            )
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=result_fmt.closed_fund_prompt(results),
                    reply_markup=superadmin_tournament_close_kb.admin_closed_fund_input_keyboard(
                        tournament_id=callback_data.tournament_id,
                        page=callback_data.page,
                    ),
                )
            return
        if (
            callback_data.action
            == superadmin_tournament_close_kb.AdminClosedCorrectionAction.FINISH
        ):
            draft = await _closed_correction_draft(
                callback.from_user.id,
                callback_data.tournament_id,
                state,
            )
            result = await result_service.build_closed_tournament_correction_preview(
                callback.from_user.id,
                draft,
            )
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=result_fmt.closed_correction_summary(result),
                    reply_markup=superadmin_tournament_close_kb.admin_closed_correction_preview_keyboard(
                        tournament_id=callback_data.tournament_id,
                        page=callback_data.page,
                    ),
                )
            return
        if (
            callback_data.action
            == superadmin_tournament_close_kb.AdminClosedCorrectionAction.CONFIRM
        ):
            draft = await _closed_correction_draft(
                callback.from_user.id,
                callback_data.tournament_id,
                state,
            )
            result = await result_service.apply_closed_tournament_correction(
                callback.from_user.id,
                draft,
            )
            await _clear_closed_correction_draft(state, callback_data.tournament_id)
            await notify_players_about_prize_stack_bonus_corrections(
                callback.bot,
                result.player_notifications,
            )
            await callback.answer("Исправление завершено.")
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=result_fmt.closed_correction_summary(result),
                    reply_markup=superadmin_tournament_close_kb.admin_closed_correction_card_keyboard(
                        tournament_id=callback_data.tournament_id,
                        page=callback_data.page,
                    ),
                )
            return
    except AdminAccessDeniedError:
        await callback.answer(text.ACCESS_DENIED, show_alert=True)
        return
    except ResultValidationError as error:
        await callback.answer()
        if callback.message is not None:
            await callback.message.answer(result_fmt.close_tournament_blocked(error.errors))
        return
    except ResultTournamentNotFoundError:
        await callback.answer(text.ADMIN_RESULTS_NOT_FOUND, show_alert=True)
        return
    except ClosedTournamentCorrectionStaleError:
        await state.clear()
        await callback.answer("Исправление устарело. Открой турнир заново.", show_alert=True)
        return
    await callback.answer(text.ADMIN_RESULTS_NOT_FOUND, show_alert=True)


@router.callback_query(superadmin_tournament_close_kb.AdminClosedResultPlayerCallback.filter())
async def select_closed_result_player(
    callback: CallbackQuery,
    callback_data: superadmin_tournament_close_kb.AdminClosedResultPlayerCallback,
    state: FSMContext,
) -> None:
    try:
        if (
            callback_data.action
            == superadmin_tournament_close_kb.AdminClosedResultPlayerAction.CANCEL
        ):
            await state.clear()
            await callback.answer(text.ADMIN_RESULTS_CANCELLED)
            await _return_to_superadmin_menu(callback, text.ADMIN_RESULTS_CANCELLED)
            return
        draft = await _closed_correction_draft(
            callback.from_user.id,
            callback_data.tournament_id,
            state,
        )
        results = await result_service.get_closed_tournament_draft_results(
            callback.from_user.id,
            draft,
        )
        page = pagination_service.paginate(
            results.players,
            page=callback_data.page,
            page_size=admin_results_kb.ADMIN_RESULT_PAGE_SIZE,
        )
        if (
            callback_data.action
            == superadmin_tournament_close_kb.AdminClosedResultPlayerAction.ADD_SEARCH
        ):
            await state.set_state(AdminResultStates.entering_closed_add_player_search)
            await state.update_data(
                closed_add_tournament_id=callback_data.tournament_id,
                closed_add_page=callback_data.page,
            )
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=result_fmt.closed_add_player_search_prompt(results),
                    reply_markup=superadmin_tournament_close_kb.admin_closed_add_player_search_results_keyboard(
                        tournament_id=callback_data.tournament_id,
                        page=callback_data.page,
                        players=[],
                    ),
                )
            return
        if (
            callback_data.action
            == superadmin_tournament_close_kb.AdminClosedResultPlayerAction.ADD_CONFIRM
        ):
            results, user = await result_service.get_closed_draft_add_player_confirmation(
                callback.from_user.id,
                draft,
                user_id=callback_data.target_player_id,
            )
            await state.set_state(None)
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=result_fmt.closed_add_player_confirmation(results, user),
                    reply_markup=superadmin_tournament_close_kb.admin_closed_add_player_confirmation_keyboard(
                        tournament_id=callback_data.tournament_id,
                        page=callback_data.page,
                        target_player_id=callback_data.target_player_id,
                    ),
                )
            return
        if (
            callback_data.action
            == superadmin_tournament_close_kb.AdminClosedResultPlayerAction.ADD_APPLY
        ):
            draft = await result_service.add_closed_tournament_draft_existing_player(
                callback.from_user.id,
                draft,
                user_id=callback_data.target_player_id,
            )
            await _store_closed_correction_draft(state, draft)
            results = await result_service.get_closed_tournament_draft_results(
                callback.from_user.id,
                draft,
            )
            await callback.answer("Игрок добавлен в черновик.")
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=result_fmt.closed_correction_players(results),
                    reply_markup=superadmin_tournament_close_kb.admin_closed_players_menu_keyboard(
                        tournament_id=callback_data.tournament_id,
                        page=callback_data.page,
                    ),
                )
            return
        if (
            callback_data.action
            == superadmin_tournament_close_kb.AdminClosedResultPlayerAction.DELETE_LIST
        ):
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=result_fmt.closed_correction_players(results),
                    reply_markup=superadmin_tournament_close_kb.admin_closed_delete_player_list_keyboard(
                        results,
                        page=callback_data.page,
                    ),
                )
            return
        if (
            callback_data.action
            == superadmin_tournament_close_kb.AdminClosedResultPlayerAction.DELETE_PREVIEW
        ):
            player = ResultService.find_result_player(results, callback_data.player_id)
            if player is None:
                await callback.answer(result_text.PLAYER_NOT_FOUND, show_alert=True)
                return
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=result_fmt.closed_delete_player_confirmation(results, player),
                    reply_markup=superadmin_tournament_close_kb.admin_closed_delete_player_confirmation_keyboard(
                        tournament_id=callback_data.tournament_id,
                        page=callback_data.page,
                        player_id=callback_data.player_id,
                    ),
                )
            return
        if (
            callback_data.action
            == superadmin_tournament_close_kb.AdminClosedResultPlayerAction.DELETE_APPLY
        ):
            draft = await result_service.delete_closed_tournament_draft_player(
                callback.from_user.id,
                draft,
                player_id=callback_data.player_id,
            )
            await _store_closed_correction_draft(state, draft)
            results = await result_service.get_closed_tournament_draft_results(
                callback.from_user.id,
                draft,
            )
            await callback.answer("Игрок удалён из черновика.")
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=result_fmt.closed_correction_players(results),
                    reply_markup=superadmin_tournament_close_kb.admin_closed_players_menu_keyboard(
                        tournament_id=callback_data.tournament_id,
                        page=callback_data.page,
                    ),
                )
            return
        if (
            callback_data.action
            == superadmin_tournament_close_kb.AdminClosedResultPlayerAction.PAGE
        ):
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=result_fmt.players_table(results, page),
                    reply_markup=superadmin_tournament_close_kb.admin_closed_result_players_keyboard(
                        results,
                        page,
                    ),
                    parse_mode=RESULT_SUMMARY_PARSE_MODE,
                )
            return
        player = ResultService.find_result_player(results, callback_data.player_id)
        if player is None:
            await callback.answer(result_text.PLAYER_NOT_FOUND, show_alert=True)
            return
        if (
            callback_data.action
            == superadmin_tournament_close_kb.AdminClosedResultPlayerAction.REPLACE
        ):
            await state.set_state(AdminResultStates.entering_closed_result_replacement_search)
            await state.update_data(
                closed_replace_tournament_id=callback_data.tournament_id,
                closed_replace_current_player_id=callback_data.player_id,
                closed_replace_page=callback_data.page,
            )
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=f"Кого поставить вместо {player.display_name}?\n\nВведи имя игрока.",
                    reply_markup=superadmin_tournament_close_kb.admin_closed_replacement_input_keyboard(
                        tournament_id=callback_data.tournament_id,
                        page=callback_data.page,
                        current_player_id=callback_data.player_id,
                    ),
                )
            return
        await callback.answer()
        if callback.message is not None:
            await edit_message_if_changed(
                callback.message,
                text=result_fmt.player_detail(results, player),
                reply_markup=superadmin_tournament_close_kb.admin_closed_result_player_fields_keyboard(
                    results,
                    player,
                    callback_data.page,
                ),
            )
    except AdminAccessDeniedError:
        await callback.answer(text.ACCESS_DENIED, show_alert=True)
    except ResultTournamentNotFoundError:
        await callback.answer(text.ADMIN_RESULTS_NOT_FOUND, show_alert=True)
    except ClosedTournamentCorrectionStaleError:
        await state.clear()
        await callback.answer("Исправление устарело. Открой турнир заново.", show_alert=True)


@router.callback_query(superadmin_tournament_close_kb.AdminClosedResultFieldCallback.filter())
async def select_closed_result_field(
    callback: CallbackQuery,
    callback_data: superadmin_tournament_close_kb.AdminClosedResultFieldCallback,
    state: FSMContext,
) -> None:
    try:
        if (
            callback_data.action
            == superadmin_tournament_close_kb.AdminClosedResultFieldAction.CANCEL
        ):
            await state.clear()
            await callback.answer(text.ADMIN_RESULTS_CANCELLED)
            await _return_to_superadmin_menu(callback, text.ADMIN_RESULTS_CANCELLED)
            return
        draft = await _closed_correction_draft(
            callback.from_user.id,
            callback_data.tournament_id,
            state,
        )
        results = await result_service.get_closed_tournament_draft_results(
            callback.from_user.id,
            draft,
        )
        player = ResultService.find_result_player(results, callback_data.player_id)
        if player is None:
            await callback.answer(result_text.PLAYER_NOT_FOUND, show_alert=True)
            return
        await callback.answer()
        if callback.message is not None:
            await edit_message_if_changed(
                callback.message,
                text=result_fmt.field_prompt(
                    player,
                    _closed_result_field_name(callback_data.field, results),
                ),
                reply_markup=superadmin_tournament_close_kb.admin_closed_result_value_keyboard(
                    tournament_id=callback_data.tournament_id,
                    page=callback_data.page,
                    player_id=callback_data.player_id,
                    field=callback_data.field,
                    occupied_places=ResultService.occupied_result_places(results),
                    current_place=player.place,
                ),
            )
    except AdminAccessDeniedError:
        await callback.answer(text.ACCESS_DENIED, show_alert=True)
    except ResultTournamentNotFoundError:
        await callback.answer(text.ADMIN_RESULTS_NOT_FOUND, show_alert=True)
    except ClosedTournamentCorrectionStaleError:
        await state.clear()
        await callback.answer("Исправление устарело. Открой турнир заново.", show_alert=True)


@router.callback_query(superadmin_tournament_close_kb.AdminClosedResultValueCallback.filter())
async def select_closed_result_value(
    callback: CallbackQuery,
    callback_data: superadmin_tournament_close_kb.AdminClosedResultValueCallback,
    state: FSMContext,
) -> None:
    try:
        if (
            callback_data.action
            == superadmin_tournament_close_kb.AdminClosedResultValueAction.CANCEL
        ):
            await state.clear()
            await callback.answer(text.ADMIN_RESULTS_CANCELLED)
            await _return_to_superadmin_menu(callback, text.ADMIN_RESULTS_CANCELLED)
            return
        service_field = ResultField(callback_data.field.value)
        if callback_data.action == superadmin_tournament_close_kb.AdminClosedResultValueAction.SET:
            draft = await _closed_correction_draft(
                callback.from_user.id,
                callback_data.tournament_id,
                state,
            )
            draft = await result_service.update_closed_tournament_draft_result_field(
                callback.from_user.id,
                draft,
                player_id=callback_data.player_id,
                field=service_field,
                value=callback_data.value,
            )
            await _store_closed_correction_draft(state, draft)
            results = await result_service.get_closed_tournament_draft_results(
                callback.from_user.id,
                draft,
            )
            player = ResultService.find_result_player(results, callback_data.player_id)
            if player is None:
                await callback.answer(result_text.PLAYER_NOT_FOUND, show_alert=True)
                return
            await callback.answer(result_text.ADMIN_RESULTS_SAVED)
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=result_fmt.player_detail(results, player),
                    reply_markup=superadmin_tournament_close_kb.admin_closed_result_player_fields_keyboard(
                        results,
                        player,
                        callback_data.page,
                    ),
                )
            return
        draft = await _closed_correction_draft(
            callback.from_user.id,
            callback_data.tournament_id,
            state,
        )
        results = await result_service.get_closed_tournament_draft_results(
            callback.from_user.id,
            draft,
        )
        player = ResultService.find_result_player(results, callback_data.player_id)
        if player is None:
            await callback.answer(result_text.PLAYER_NOT_FOUND, show_alert=True)
            return
        await callback.answer()
        if callback.message is not None:
            await edit_message_if_changed(
                callback.message,
                text=result_fmt.player_detail(results, player),
                reply_markup=superadmin_tournament_close_kb.admin_closed_result_player_fields_keyboard(
                    results,
                    player,
                    callback_data.page,
                ),
            )
    except AdminAccessDeniedError:
        await callback.answer(text.ACCESS_DENIED, show_alert=True)
    except ResultTournamentNotFoundError:
        await callback.answer(text.ADMIN_RESULTS_NOT_FOUND, show_alert=True)
    except ClosedTournamentCorrectionStaleError:
        await state.clear()
        await callback.answer("Исправление устарело. Открой турнир заново.", show_alert=True)
    except (ResultInvalidPlayerDataError, ResultUserNotFoundError, ValueError):
        await callback.answer("Некорректное значение.", show_alert=True)


@router.callback_query(superadmin_tournament_close_kb.AdminClosedResultReplacementCallback.filter())
async def select_closed_result_replacement(
    callback: CallbackQuery,
    callback_data: superadmin_tournament_close_kb.AdminClosedResultReplacementCallback,
    state: FSMContext,
) -> None:
    try:
        if (
            callback_data.action
            == superadmin_tournament_close_kb.AdminClosedResultReplacementAction.CANCEL
        ):
            await state.clear()
            await callback.answer(text.ADMIN_RESULTS_CANCELLED)
            await _return_to_superadmin_menu(callback, text.ADMIN_RESULTS_CANCELLED)
            return
        if (
            callback_data.action
            == superadmin_tournament_close_kb.AdminClosedResultReplacementAction.BACK
        ):
            await state.set_state(None)
            await _edit_closed_result_player_detail(
                callback=callback,
                state=state,
                tournament_id=callback_data.tournament_id,
                page=callback_data.page,
                player_id=callback_data.current_player_id,
            )
            return
        if (
            callback_data.action
            == superadmin_tournament_close_kb.AdminClosedResultReplacementAction.CONFIRM
        ):
            draft = await _closed_correction_draft(
                callback.from_user.id,
                callback_data.tournament_id,
                state,
            )
            (
                results,
                current_player,
                user,
            ) = await result_service.get_closed_draft_replacement_confirmation(
                callback.from_user.id,
                draft,
                current_player_id=callback_data.current_player_id,
                new_player_id=callback_data.new_player_id,
            )
            await state.set_state(None)
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=result_fmt.replace_result_player_prompt(
                        results.tournament,
                        current_player,
                        user,
                    ),
                    reply_markup=superadmin_tournament_close_kb.admin_closed_replacement_confirmation_keyboard(
                        tournament_id=callback_data.tournament_id,
                        page=callback_data.page,
                        current_player_id=callback_data.current_player_id,
                        new_player_id=callback_data.new_player_id,
                    ),
                )
            return
        if (
            callback_data.action
            == superadmin_tournament_close_kb.AdminClosedResultReplacementAction.APPLY
        ):
            draft = await _closed_correction_draft(
                callback.from_user.id,
                callback_data.tournament_id,
                state,
            )
            draft = await result_service.replace_closed_tournament_draft_result_player(
                callback.from_user.id,
                draft,
                current_player_id=callback_data.current_player_id,
                new_player_id=callback_data.new_player_id,
            )
            await _store_closed_correction_draft(state, draft)
            results = await result_service.get_closed_tournament_draft_results(
                callback.from_user.id,
                draft,
            )
            await state.set_state(None)
            player = ResultService.find_result_player(results, callback_data.new_player_id)
            await callback.answer(result_text.ADMIN_RESULTS_SAVED)
            if callback.message is not None and player is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=result_fmt.player_detail(results, player),
                    reply_markup=superadmin_tournament_close_kb.admin_closed_result_player_fields_keyboard(
                        results,
                        player,
                        callback_data.page,
                    ),
                )
            return
    except AdminAccessDeniedError:
        await callback.answer(text.ACCESS_DENIED, show_alert=True)
    except ResultPlayerAlreadyAddedError:
        await callback.answer("Этот игрок уже добавлен в турнир.", show_alert=True)
    except ClosedTournamentCorrectionStaleError:
        await state.clear()
        await callback.answer("Исправление устарело. Открой турнир заново.", show_alert=True)
    except (ResultTournamentNotFoundError, ResultUserNotFoundError):
        await callback.answer(text.ADMIN_RESULTS_NOT_FOUND, show_alert=True)


@router.callback_query(superadmin_tournament_close_kb.AdminClosedFundCallback.filter())
async def select_closed_fund_action(
    callback: CallbackQuery,
    callback_data: superadmin_tournament_close_kb.AdminClosedFundCallback,
    state: FSMContext,
) -> None:
    if callback_data.action == superadmin_tournament_close_kb.AdminClosedFundAction.CANCEL:
        await state.clear()
        await callback.answer(text.ADMIN_RESULTS_CANCELLED)
        await _return_to_superadmin_menu(callback, text.ADMIN_RESULTS_CANCELLED)
        return
    await state.set_state(None)
    await _edit_closed_correction_card(
        callback,
        state,
        tournament_id=callback_data.tournament_id,
        page=callback_data.page,
    )


async def _send_calendar_planning_notification_after_close(
    callback: CallbackQuery,
    closed_tournament_date: date,
) -> None:
    if callback.message is None:
        return
    try:
        planning = await tournament_planning_service.inspect_after_tournament_close(
            callback.from_user.id,
            closed_tournament_date,
        )
    except (
        AdminAccessDeniedError,
        CalendarDefaultTournamentTypeNotFoundError,
        CalendarWeeklyPlanIntegrityError,
    ):
        logger.exception("Failed to inspect weekly tournament planning after close")
        return

    if planning.status == WeeklyPlanningStatus.READY and planning.plan is not None:
        await callback.message.answer(calendar_text.ADMIN_CALENDAR_TOURNAMENT_WEEK_EMPTY)
        await callback.message.answer(
            schedule_fmt.plan_preview(planning.plan),
            reply_markup=admin_schedule_kb.manual_tournaments_plan_keyboard(planning.plan),
        )


async def _publish_result_report(callback: CallbackQuery, preview: object) -> object:
    report = publication_fmt.result_publication_report(preview)
    sent: list[str] = []
    failed: list[str] = []
    already_published: list[str] = []
    for destination in preview.destinations:
        if destination.already_published:
            already_published.append(destination.destination_type)
            continue
        try:
            message_id = await _send_publication_media(
                callback.bot,
                chat_id=destination.chat_id,
                photos=preview.photos,
                report=report,
            )
        except TelegramAPIError:
            logger.exception("Failed to publish tournament results")
            failed.append(destination.destination_type)
            continue
        await tournament_publication_service.record_publication_success(
            superadmin_telegram_id=callback.from_user.id,
            tournament_id=preview.tournament.id,
            publication_type=TournamentPublicationType.RESULTS,
            destination_type=TournamentPublicationDestination(destination.destination_type),
            destination_chat_id=destination.chat_id,
            content_hash=preview.content_hash,
            telegram_message_id=message_id,
        )
        sent.append(destination.destination_type)
    return tournament_publication_service.delivery_summary(
        sent=sent,
        failed=failed,
        already_published=already_published,
    )


async def _send_publication_media(
    bot: Bot,
    *,
    chat_id: int,
    photos: list[object],
    report: str,
) -> int | None:
    primary_message_id, _message_ids = await _send_publication_media_with_ids(
        bot,
        chat_id=chat_id,
        photos=photos,
        report=report,
    )
    return primary_message_id


async def _send_publication_media_with_ids(
    bot: Bot,
    *,
    chat_id: int,
    photos: list[object],
    report: str,
) -> tuple[int | None, list[int]]:
    if not photos:
        sent = await bot.send_message(chat_id=chat_id, text=report)
        return sent.message_id, [sent.message_id]

    if len(photos) == 1:
        if len(report) <= publication_fmt.CAPTION_LIMIT:
            sent = await bot.send_photo(
                chat_id=chat_id,
                photo=photos[0].telegram_file_id,
                caption=report,
            )
            return sent.message_id, [sent.message_id]

        photo_message = await bot.send_photo(
            chat_id=chat_id,
            photo=photos[0].telegram_file_id,
        )
        report_message = await bot.send_message(
            chat_id=chat_id,
            text=report,
        )
        return report_message.message_id, [
            photo_message.message_id,
            report_message.message_id,
        ]

    media = [
        InputMediaPhoto(
            media=photo.telegram_file_id,
            caption=report if index == 0 and len(report) <= publication_fmt.CAPTION_LIMIT else None,
        )
        for index, photo in enumerate(photos[:10])
    ]
    sent_group = await bot.send_media_group(
        chat_id=chat_id,
        media=media,
    )
    message_ids = [sent.message_id for sent in sent_group]

    if len(report) > publication_fmt.CAPTION_LIMIT:
        report_message = await bot.send_message(
            chat_id=chat_id,
            text=report,
        )
        message_ids.append(report_message.message_id)
        return report_message.message_id, message_ids

    first = sent_group[0] if sent_group else None
    return getattr(first, "message_id", None), message_ids


@router.message(AdminResultStates.entering_closed_add_player_search)
async def enter_closed_add_player_search(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return
    data = await state.get_data()
    tournament_id = int(data["closed_add_tournament_id"])
    page = int(data["closed_add_page"])
    try:
        draft = await _closed_correction_draft(
            message.from_user.id,
            tournament_id,
            state,
        )
        players = await result_service.search_closed_draft_add_player_users(
            message.from_user.id,
            draft,
            query=message.text or "",
        )
    except AdminAccessDeniedError:
        await state.clear()
        await message.answer(text.ACCESS_DENIED)
        return
    except ResultTournamentNotFoundError:
        await state.clear()
        await message.answer(text.ADMIN_RESULTS_NOT_FOUND)
        return
    except ClosedTournamentCorrectionStaleError:
        await state.clear()
        await message.answer("Исправление устарело. Открой турнир заново.")
        return
    except TournamentResultsEditingUnavailableError:
        await state.clear()
        await message.answer("Турнир недоступен для редактирования.")
        return

    if not players:
        await message.answer("Игроки не найдены.")
        return
    await message.answer(
        "Нашел игроков в базе:",
        reply_markup=superadmin_tournament_close_kb.admin_closed_add_player_search_results_keyboard(
            tournament_id=tournament_id,
            page=page,
            players=players,
        ),
    )


@router.message(AdminResultStates.entering_closed_result_replacement_search)
async def enter_closed_result_replacement_search(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return
    data = await state.get_data()
    tournament_id = int(data["closed_replace_tournament_id"])
    current_player_id = int(data["closed_replace_current_player_id"])
    page = int(data["closed_replace_page"])
    try:
        draft = await _closed_correction_draft(
            message.from_user.id,
            tournament_id,
            state,
        )
        players = await result_service.search_closed_draft_replacement_users(
            message.from_user.id,
            draft,
            current_player_id=current_player_id,
            query=message.text or "",
        )
    except AdminAccessDeniedError:
        await state.clear()
        await message.answer(text.ACCESS_DENIED)
        return
    except ResultTournamentNotFoundError:
        await state.clear()
        await message.answer(text.ADMIN_RESULTS_NOT_FOUND)
        return
    except ClosedTournamentCorrectionStaleError:
        await state.clear()
        await message.answer("Исправление устарело. Открой турнир заново.")
        return
    except TournamentResultsEditingUnavailableError:
        await state.clear()
        await message.answer("Турнир недоступен для редактирования.")
        return

    if not players:
        await message.answer("Игроки не найдены.")
        return
    await message.answer(
        "Нашел игроков в базе:",
        reply_markup=superadmin_tournament_close_kb.admin_closed_replacement_search_results_keyboard(
            tournament_id=tournament_id,
            page=page,
            current_player_id=current_player_id,
            players=players,
        ),
    )


@router.message(AdminResultStates.entering_closed_tournament_fund)
async def enter_closed_tournament_fund(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return
    data = await state.get_data()
    tournament_id = int(data["closed_fund_tournament_id"])
    page = int(data["closed_fund_page"])
    try:
        draft = await _closed_correction_draft(
            message.from_user.id,
            tournament_id,
            state,
        )
        draft = await result_service.update_closed_tournament_draft_fund(
            message.from_user.id,
            draft,
            tournament_fund=int(message.text or ""),
        )
        await _store_closed_correction_draft(state, draft)
        results = await result_service.get_closed_tournament_draft_results(
            message.from_user.id,
            draft,
        )
    except AdminAccessDeniedError:
        await state.clear()
        await message.answer(text.ACCESS_DENIED)
        return
    except ResultTournamentNotFoundError:
        await state.clear()
        await message.answer(text.ADMIN_RESULTS_NOT_FOUND)
        return
    except ClosedTournamentCorrectionStaleError:
        await state.clear()
        await message.answer("Исправление устарело. Открой турнир заново.")
        return
    except (ResultInvalidFundError, ValueError):
        await message.answer(
            result_fmt.tournament_fund_error(),
            reply_markup=superadmin_tournament_close_kb.admin_closed_fund_input_keyboard(
                tournament_id=tournament_id,
                page=page,
            ),
        )
        return

    await state.set_state(None)
    await message.answer(
        result_fmt.closed_fund_card(results),
        reply_markup=superadmin_tournament_close_kb.admin_closed_fund_keyboard(
            tournament_id=tournament_id,
            page=page,
        ),
    )


async def _send_close_tournament_card(
    *,
    message: Message,
    state: FSMContext,
    superadmin_telegram_id: int,
    tournament_id: int,
    page: int,
) -> None:
    results = await result_service.get_closeable_tournament_results(
        superadmin_telegram_id=superadmin_telegram_id,
        tournament_id=tournament_id,
    )
    readiness = await result_service.get_close_readiness(
        superadmin_telegram_id=superadmin_telegram_id,
        tournament_id=tournament_id,
    )
    if not readiness.is_ready:
        await state.clear()
        await message.answer(
            result_fmt.close_tournament_blocked(readiness.reasons),
            reply_markup=superadmin_tournament_close_kb.admin_close_tournament_cancel_keyboard(
                tournament_id=tournament_id,
                page=page,
            ),
        )
        return
    sent_message = await message.answer(
        result_fmt.close_tournament_card(results),
        reply_markup=superadmin_tournament_close_kb.admin_close_tournament_card_keyboard(
            tournament_id=tournament_id,
            page=page,
        ),
        parse_mode=RESULT_SUMMARY_PARSE_MODE,
    )
    await _set_fund_input_state(
        state,
        tournament_id=tournament_id,
        page=page,
        prompt_message=sent_message,
    )


async def _edit_close_tournament_card(
    *,
    callback: CallbackQuery,
    state: FSMContext,
    tournament_id: int,
    page: int,
    return_context: dict[str, int | str] | None = None,
) -> None:
    readiness = await result_service.get_close_readiness(
        superadmin_telegram_id=callback.from_user.id,
        tournament_id=tournament_id,
    )
    if not readiness.is_ready:
        await state.clear()
        await edit_message_if_changed(
            callback.message,
            text=result_fmt.close_tournament_blocked(readiness.reasons),
            reply_markup=superadmin_tournament_close_kb.admin_close_tournament_cancel_keyboard(
                tournament_id=tournament_id,
                page=page,
            ),
        )
        return
    await edit_message_if_changed(
        callback.message,
        text=result_fmt.tournament_fund_prompt(readiness.tournament),
        reply_markup=superadmin_tournament_close_kb.admin_close_tournament_card_keyboard(
            tournament_id=tournament_id,
            page=page,
        ),
    )
    await _set_fund_input_state(
        state,
        tournament_id=tournament_id,
        page=page,
        prompt_message=callback.message,
        return_context=return_context,
    )


async def open_close_tournament_card_from_tournament_hub(
    *,
    callback: CallbackQuery,
    state: FSMContext,
    tournament_id: int,
    page: int,
) -> None:
    await _edit_close_tournament_card(
        callback=callback,
        state=state,
        tournament_id=tournament_id,
        page=page,
        return_context={
            "close_return_context": _CLOSE_RETURN_CONTEXT_OPEN_TOURNAMENTS,
            "close_return_page": page,
        },
    )


async def _edit_closed_correction_list(callback: CallbackQuery, *, page: int) -> None:
    tournaments = await result_service.list_closed_tournaments_for_superadmin(callback.from_user.id)
    page_view = pagination_service.paginate(
        tournaments,
        page=page,
        page_size=admin_results_kb.ADMIN_RESULT_PAGE_SIZE,
    )
    await callback.answer()
    if callback.message is None:
        return
    await edit_message_if_changed(
        callback.message,
        text=result_fmt.closed_correction_tournament_list(page_view),
        reply_markup=superadmin_tournament_close_kb.admin_closed_correction_tournament_list_keyboard(
            page_view
        ),
    )


async def open_closed_tournament_list_from_tournament_hub(
    *,
    callback: CallbackQuery,
    page: int,
) -> None:
    await _edit_closed_correction_list(callback, page=page)


async def _edit_closed_correction_card(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    tournament_id: int,
    page: int,
) -> None:
    draft = await _closed_correction_draft(
        callback.from_user.id,
        tournament_id,
        state,
    )
    results = await result_service.get_closed_tournament_draft_results(
        callback.from_user.id,
        draft,
    )
    await callback.answer()
    if callback.message is None:
        return
    await edit_message_if_changed(
        callback.message,
        text=result_fmt.closed_correction_tournament_card(results),
        reply_markup=superadmin_tournament_close_kb.admin_closed_correction_card_keyboard(
            tournament_id=tournament_id,
            page=page,
        ),
    )


async def _edit_tournament_hub(callback: CallbackQuery) -> None:
    hub = await tournament_planning_service.get_superadmin_tournament_hub(callback.from_user.id)
    await callback.answer()
    if callback.message is None:
        return
    await edit_message_if_changed(
        callback.message,
        text=tournaments_text.TOURNAMENT_HUB_TITLE,
        reply_markup=superadmin_tournaments_kb.tournament_hub_keyboard(hub.open_tournaments_count),
    )


def _closed_correction_draft_key(tournament_id: int) -> str:
    return f"closed_correction_draft_{tournament_id}"


async def _closed_correction_draft(
    superadmin_telegram_id: int,
    tournament_id: int,
    state: FSMContext,
    *,
    reset: bool = False,
) -> ClosedTournamentCorrectionDraftView:
    key = _closed_correction_draft_key(tournament_id)
    data = await state.get_data()
    draft = None if reset else ResultService.correction_draft_from_payload(data.get(key))
    if draft is None:
        draft = await result_service.begin_closed_tournament_correction(
            superadmin_telegram_id,
            tournament_id,
        )
        await _store_closed_correction_draft(state, draft)
    return draft


async def _store_closed_correction_draft(
    state: FSMContext,
    draft: ClosedTournamentCorrectionDraftView,
) -> None:
    await state.update_data(
        **{
            _closed_correction_draft_key(draft.tournament_id): (
                ResultService.correction_draft_to_payload(draft)
            )
        }
    )


async def _clear_closed_correction_draft(state: FSMContext, tournament_id: int) -> None:
    await state.update_data(**{_closed_correction_draft_key(tournament_id): None})


async def _edit_closed_result_player_detail(
    *,
    callback: CallbackQuery,
    state: FSMContext,
    tournament_id: int,
    page: int,
    player_id: int,
) -> None:
    draft = await _closed_correction_draft(
        callback.from_user.id,
        tournament_id,
        state,
    )
    results = await result_service.get_closed_tournament_draft_results(
        callback.from_user.id,
        draft,
    )
    player = ResultService.find_result_player(results, player_id)
    if player is None:
        await callback.answer(result_text.PLAYER_NOT_FOUND, show_alert=True)
        return
    await callback.answer()
    if callback.message is None:
        return
    await edit_message_if_changed(
        callback.message,
        text=result_fmt.player_detail(results, player),
        reply_markup=superadmin_tournament_close_kb.admin_closed_result_player_fields_keyboard(
            results,
            player,
            page,
        ),
    )


def _closed_result_field_name(
    field: superadmin_tournament_close_kb.AdminClosedResultField,
    results: object,
) -> str:
    if field == superadmin_tournament_close_kb.AdminClosedResultField.KNOCKOUTS:
        return "🥊"
    if field == superadmin_tournament_close_kb.AdminClosedResultField.BIG_KNOCKOUTS:
        return "Босс КО"
    if field == superadmin_tournament_close_kb.AdminClosedResultField.BONUS:
        return str(getattr(results, "bonus_points_label", "бонус")).lower()
    return "место"


async def _return_to_superadmin_menu(callback: CallbackQuery, message_text: str) -> None:
    if callback.message is None:
        return
    await _delete_callback_message(callback)
    await send_superadmin_panel(
        callback.message,
        superadmin_telegram_id=callback.from_user.id,
        text=message_text,
    )


async def _prepare_fund_input_state(
    *,
    state: FSMContext,
    superadmin_telegram_id: int,
    tournament_id: int,
    page: int,
) -> None:
    errors = await result_service.validate_closeable_results(
        superadmin_telegram_id=superadmin_telegram_id,
        tournament_id=tournament_id,
    )
    if errors:
        raise ResultValidationError(errors)
    await _set_fund_input_state(state, tournament_id=tournament_id, page=page)


async def _set_fund_input_state(
    state: FSMContext,
    *,
    tournament_id: int,
    page: int,
    prompt_message: Message | None = None,
    return_context: dict[str, int | str] | None = None,
) -> None:
    await state.clear()
    await state.set_state(AdminResultStates.entering_tournament_fund)
    data: dict[str, int | str] = {
        "close_tournament_id": tournament_id,
        "close_tournament_page": page,
    }
    identity = _message_identity(prompt_message)
    if identity is not None:
        chat_id, message_id = identity
        data["close_tournament_prompt_chat_id"] = chat_id
        data["close_tournament_prompt_message_id"] = message_id
    if return_context is not None:
        data.update(return_context)
    await state.update_data(**data)


def _close_return_context_from_state(data: dict[str, object]) -> dict[str, int | str] | None:
    if data.get("close_return_context") != _CLOSE_RETURN_CONTEXT_OPEN_TOURNAMENTS:
        return None
    return {
        "close_return_context": _CLOSE_RETURN_CONTEXT_OPEN_TOURNAMENTS,
        "close_return_page": int(data.get("close_return_page", 0)),
    }


async def _edit_open_tournaments_return_context(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    page: int,
) -> None:
    page_view = await tournament_planning_service.list_open_tournaments_for_superadmin(
        callback.from_user.id,
        page=page,
    )
    await state.clear()
    await callback.answer()
    if callback.message is None:
        return
    await edit_message_if_changed(
        callback.message,
        text=tournament_fmt.superadmin_open_list(page_view),
        reply_markup=superadmin_tournaments_kb.open_tournament_list_keyboard(page_view),
    )


async def _edit_close_tournament_root(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    page: int,
) -> None:
    tournaments = await result_service.list_unclosed_tournaments_for_superadmin(
        callback.from_user.id
    )
    ready = [item for item in tournaments if item.is_ready]
    await state.clear()
    await callback.answer()
    if callback.message is None:
        return
    if not ready:
        await _delete_callback_message(callback)
        await send_superadmin_panel(
            callback.message,
            superadmin_telegram_id=callback.from_user.id,
            text=text.NO_READY_TOURNAMENTS,
        )
        return
    page_view = pagination_service.paginate(
        tournaments,
        page=page,
        page_size=admin_results_kb.ADMIN_RESULT_PAGE_SIZE,
    )
    await edit_message_if_changed(
        callback.message,
        text=result_fmt.close_tournament_list(page_view),
        reply_markup=superadmin_tournament_close_kb.admin_close_tournament_list_keyboard(
            page_view,
        ),
    )


@router.message(AdminResultStates.entering_tournament_fund)
async def enter_tournament_fund(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return

    data = await state.get_data()
    tournament_id = int(data["close_tournament_id"])
    page_number = int(data.get("close_tournament_page", 0))
    try:
        tournament_fund = ResultService.validate_tournament_fund(int(message.text or ""))
        preview = await tournament_publication_service.get_pre_close_result_publication_preview(
            superadmin_telegram_id=message.from_user.id,
            tournament_id=tournament_id,
            tournament_fund=tournament_fund,
        )
        results = await result_service.get_closeable_tournament_results(
            superadmin_telegram_id=message.from_user.id,
            tournament_id=tournament_id,
        )
    except AdminAccessDeniedError:
        await state.clear()
        await message.answer(text.ACCESS_DENIED)
        return
    except ResultTournamentNotFoundError:
        await state.clear()
        await message.answer(text.ADMIN_RESULTS_NOT_FOUND)
        return
    except FutureTournamentCannotBeClosedError:
        await state.clear()
        await message.answer("Будущий турнир нельзя закрыть.")
        return
    except (ValueError, ResultInvalidFundError):
        await message.answer(
            result_fmt.tournament_fund_error_prompt(),
            reply_markup=superadmin_tournament_close_kb.admin_close_tournament_fund_error_keyboard(
                tournament_id=tournament_id,
                page=page_number,
            ),
        )
        return

    await state.update_data(tournament_fund=int(tournament_fund))
    await state.set_state(None)
    await _disable_fund_prompt_keyboard(message, data)

    report = publication_fmt.result_publication_report(preview)

    _, preview_message_ids = await _send_publication_media_with_ids(
        message.bot,
        chat_id=message.chat.id,
        photos=preview.photos,
        report=report,
    )

    await state.update_data(
        close_publication_preview_message_ids=preview_message_ids,
    )

    await message.answer(
        result_fmt.close_tournament_preview_confirmation(results),
        reply_markup=superadmin_tournament_close_kb.admin_close_tournament_confirmation_keyboard(
            tournament_id=tournament_id,
            page=page_number,
        ),
        parse_mode=RESULT_SUMMARY_PARSE_MODE,
    )


async def _send_tournament_photos(
    callback: CallbackQuery,
    tournament_id: int,
) -> None:
    try:
        photos = await result_service.list_tournament_photos(
            admin_telegram_id=callback.from_user.id,
            tournament_id=tournament_id,
        )
    except AdminAccessDeniedError:
        await callback.answer(text.ACCESS_DENIED, show_alert=True)
        return
    except ResultTournamentNotFoundError:
        await callback.answer(text.ADMIN_RESULTS_NOT_FOUND, show_alert=True)
        return
    if not photos:
        await callback.answer("Фото турнира не добавлены.", show_alert=True)
        return
    await callback.answer()
    if callback.message is None:
        return
    await _send_photo_media(callback.message, photos)


async def _send_photo_media(message: Message, photos: list[object]) -> None:
    if len(photos) == 1:
        await message.answer_photo(photos[0].telegram_file_id)
        return
    await message.answer_media_group(
        [InputMediaPhoto(media=photo.telegram_file_id) for photo in photos]
    )


def _message_identity(message: Message | None) -> tuple[int, int] | None:
    if message is None:
        return None
    chat_id = getattr(getattr(message, "chat", None), "id", None)
    message_id = getattr(message, "message_id", None)
    if isinstance(chat_id, int) and isinstance(message_id, int):
        return chat_id, message_id
    return None


async def _disable_fund_prompt_keyboard(
    message: Message,
    data: dict[str, object],
) -> None:
    chat_id = data.get("close_tournament_prompt_chat_id")
    message_id = data.get("close_tournament_prompt_message_id")
    if not isinstance(chat_id, int) or not isinstance(message_id, int):
        return

    await edit_message_reply_markup_by_id_if_changed(
        message.bot,
        chat_id=chat_id,
        message_id=message_id,
        reply_markup=None,
    )


async def _delete_close_publication_preview(
    message: Message,
    data: dict[str, object],
) -> None:
    message_ids = data.get("close_publication_preview_message_ids")
    if not isinstance(message_ids, list):
        return

    for message_id in message_ids:
        if isinstance(message_id, int):
            await _delete_message_by_id(message, message_id)
