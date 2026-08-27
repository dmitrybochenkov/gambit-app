import logging
from collections.abc import Awaitable, Callable
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
from app.bot.telegram.photo_collection import (
    PhotoControlContext,
    refresh_photo_control_message,
    schedule_album_photo_control_refresh,
    send_media_then_restore_control,
    send_photo_control_message,
)
from app.bot.telegram.states import AdminResultStates
from app.bot.telegram.texts.admin import calendar as calendar_text
from app.bot.telegram.texts.admin import results as result_text
from app.bot.telegram.texts.superadmin import panel as panel_text
from app.bot.telegram.texts.superadmin import tournament_close as text
from app.db.models.enums import (
    TournamentCombinationType,
    TournamentPublicationDestination,
    TournamentPublicationType,
)
from app.services.access_policy import AdminAccessDeniedError
from app.services.pagination import pagination_service
from app.services.result_fields import ResultField
from app.services.result_service import (
    FutureTournamentCannotBeClosedError,
    ResultCombinationAlreadyExistsError,
    ResultCombinationNotFoundError,
    ResultDuplicateNameError,
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

_REPAIR_COMBINATION_ACTIONS = {
    superadmin_tournament_close_kb.AdminTournamentRepairAction.COMBINATIONS,
    superadmin_tournament_close_kb.AdminTournamentRepairAction.ADD_COMBINATION,
    superadmin_tournament_close_kb.AdminTournamentRepairAction.SELECT_COMBINATION_PLAYER,
    superadmin_tournament_close_kb.AdminTournamentRepairAction.SAVE_COMBINATION,
    superadmin_tournament_close_kb.AdminTournamentRepairAction.DELETE_COMBINATION_MENU,
    superadmin_tournament_close_kb.AdminTournamentRepairAction.DELETE_COMBINATION,
}

_REPAIR_PHOTO_ACTIONS = {
    superadmin_tournament_close_kb.AdminTournamentRepairAction.ADD_PHOTO,
    superadmin_tournament_close_kb.AdminTournamentRepairAction.PHOTO_DONE,
    superadmin_tournament_close_kb.AdminTournamentRepairAction.VIEW_PHOTOS,
    superadmin_tournament_close_kb.AdminTournamentRepairAction.DELETE_PHOTOS_CONFIRM,
    superadmin_tournament_close_kb.AdminTournamentRepairAction.DELETE_PHOTOS,
}

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
        closed_tournaments = await _list_closed_tournaments_or_empty(message.from_user.id)
    except AdminAccessDeniedError:
        await message.answer(panel_text.INSUFFICIENT_RIGHTS)
        return

    ready = [item for item in tournaments if item.is_ready]
    problematic = [item for item in tournaments if not item.is_ready]
    if not ready and not problematic and not closed_tournaments:
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
            has_correction_targets=bool(tournaments),
            has_closed_correction_targets=bool(closed_tournaments),
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
            closed_tournaments = await _list_closed_tournaments_or_empty(callback.from_user.id)
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
                        has_correction_targets=bool(tournaments),
                        has_closed_correction_targets=bool(closed_tournaments),
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

        if (
            callback_data.action
            == superadmin_tournament_close_kb.AdminCloseTournamentAction.CORRECTION_LIST
        ):
            tournaments = await result_service.list_unclosed_tournaments_for_superadmin(
                callback.from_user.id
            )
            page = pagination_service.paginate(
                tournaments,
                page=0,
                page_size=admin_results_kb.ADMIN_RESULT_PAGE_SIZE,
            )
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=result_fmt.correction_tournament_list(page),
                    reply_markup=superadmin_tournament_close_kb.admin_correction_tournament_list_keyboard(
                        page
                    ),
                )
            return

        if (
            callback_data.action
            == superadmin_tournament_close_kb.AdminCloseTournamentAction.CLOSED_CORRECTION_LIST
        ):
            await _edit_closed_correction_list(callback, page=0)
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
                await _send_post_close_publication_preview(
                    callback,
                    results.tournament.id,
                )
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
        if callback_data.action == superadmin_tournament_close_kb.AdminClosedCorrectionAction.OPEN:
            await _edit_closed_correction_card(
                callback,
                state,
                tournament_id=callback_data.tournament_id,
                page=callback_data.page,
            )
            return
        if callback_data.action == superadmin_tournament_close_kb.AdminClosedCorrectionAction.DATA:
            results = await result_service.get_closed_tournament_results(
                superadmin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
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
        if (
            callback_data.action
            == superadmin_tournament_close_kb.AdminClosedCorrectionAction.FINISH
        ):
            data = await state.get_data()
            snapshot = ResultService.snapshot_from_payload(
                data.get(f"closed_correction_snapshot_{callback_data.tournament_id}")
            )
            if not snapshot:
                current = await result_service.get_closed_tournament_results(
                    superadmin_telegram_id=callback.from_user.id,
                    tournament_id=callback_data.tournament_id,
                )
                snapshot = ResultService.snapshot_from_results(current)
            result = await result_service.finish_closed_tournament_correction(
                superadmin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
                original_snapshot=snapshot,
            )
            if result.result_changes:
                refreshed = await result_service.get_closed_tournament_results(
                    superadmin_telegram_id=callback.from_user.id,
                    tournament_id=callback_data.tournament_id,
                )
                await state.update_data(
                    **{
                        f"closed_correction_snapshot_{callback_data.tournament_id}": (
                            ResultService.snapshot_to_payload(
                                ResultService.snapshot_from_results(refreshed)
                            )
                        )
                    }
                )
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
        results = await result_service.get_closed_tournament_results(
            superadmin_telegram_id=callback.from_user.id,
            tournament_id=callback_data.tournament_id,
        )
        page = pagination_service.paginate(
            results.players,
            page=callback_data.page,
            page_size=admin_results_kb.ADMIN_RESULT_PAGE_SIZE,
        )
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
        results = await result_service.get_closed_tournament_results(
            superadmin_telegram_id=callback.from_user.id,
            tournament_id=callback_data.tournament_id,
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
            results = await result_service.update_closed_tournament_result_field(
                superadmin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
                player_id=callback_data.player_id,
                field=service_field,
                value=callback_data.value,
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
        results = await result_service.get_closed_tournament_results(
            superadmin_telegram_id=callback.from_user.id,
            tournament_id=callback_data.tournament_id,
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
                tournament_id=callback_data.tournament_id,
                page=callback_data.page,
                player_id=callback_data.current_player_id,
            )
            return
        if (
            callback_data.action
            == superadmin_tournament_close_kb.AdminClosedResultReplacementAction.CONFIRM
        ):
            (
                results,
                current_player,
                user,
            ) = await result_service.get_closed_result_replacement_confirmation(
                superadmin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
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
            results = await result_service.replace_closed_tournament_result_player(
                superadmin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
                current_player_id=callback_data.current_player_id,
                new_player_id=callback_data.new_player_id,
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
    except (ResultTournamentNotFoundError, ResultUserNotFoundError):
        await callback.answer(text.ADMIN_RESULTS_NOT_FOUND, show_alert=True)


@router.callback_query(superadmin_tournament_close_kb.AdminTournamentRepairCallback.filter())
async def select_repair_tournament_action(
    callback: CallbackQuery,
    callback_data: superadmin_tournament_close_kb.AdminTournamentRepairCallback,
    state: FSMContext,
) -> None:
    try:
        if (
            callback_data.action
            == superadmin_tournament_close_kb.AdminTournamentRepairAction.CANCEL
        ):
            await state.clear()
            await callback.answer(text.ADMIN_RESULTS_CANCELLED)
            await _return_to_superadmin_menu(callback, text.ADMIN_RESULTS_CANCELLED)
            return
        if callback_data.action == superadmin_tournament_close_kb.AdminTournamentRepairAction.OPEN:
            await callback.answer()
            if callback.message is not None:
                await _edit_repair_tournament_card(callback, callback_data.tournament_id)
            return
        if (
            callback_data.action
            == superadmin_tournament_close_kb.AdminTournamentRepairAction.ADD_PLAYER
        ):
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text="Кого добавить в турнир?",
                    reply_markup=superadmin_tournament_close_kb.admin_repair_add_player_mode_keyboard(
                        callback_data.tournament_id
                    ),
                )
            return
        if (
            callback_data.action
            == superadmin_tournament_close_kb.AdminTournamentRepairAction.ADD_EXISTING_SEARCH
        ):
            await state.set_state(AdminResultStates.entering_repair_existing_player_search)
            await state.update_data(repair_tournament_id=callback_data.tournament_id)
            await callback.answer()
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer("Введи имя игрока из базы.")
            return
        if (
            callback_data.action
            == superadmin_tournament_close_kb.AdminTournamentRepairAction.ADD_NEW_PLAYER
        ):
            await state.set_state(AdminResultStates.entering_repair_new_player)
            await state.update_data(repair_tournament_id=callback_data.tournament_id)
            await callback.answer()
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer("Введи имя нового игрока.")
            return
        if (
            callback_data.action
            == superadmin_tournament_close_kb.AdminTournamentRepairAction.CONFIRM_EXISTING
        ):
            tournament, user = await result_service.get_existing_player_add_confirmation(
                admin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
                user_id=callback_data.player_id,
            )
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=result_fmt.add_existing_player_prompt(tournament, user),
                    reply_markup=superadmin_tournament_close_kb.admin_repair_add_existing_confirmation_keyboard(
                        tournament_id=callback_data.tournament_id,
                        player_id=callback_data.player_id,
                    ),
                )
            return
        if (
            callback_data.action
            == superadmin_tournament_close_kb.AdminTournamentRepairAction.ADD_EXISTING
        ):
            await result_service.add_existing_player_to_tournament(
                admin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
                user_id=callback_data.player_id,
            )
            await state.clear()
            await callback.answer("Игрок добавлен.")
            if callback.message is not None:
                await _edit_repair_tournament_card(callback, callback_data.tournament_id)
            return
        if (
            callback_data.action
            == superadmin_tournament_close_kb.AdminTournamentRepairAction.CONFIRM_NEW
        ):
            data = await state.get_data()
            display_name = str(data.get("repair_new_display_name", ""))
            tournament, display_name = await result_service.get_new_player_add_confirmation(
                admin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
                display_name=display_name,
            )
            await state.set_state(AdminResultStates.confirming_repair_new_player)
            await state.update_data(
                repair_tournament_id=callback_data.tournament_id,
                repair_new_display_name=display_name,
            )
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=result_fmt.add_new_player_prompt(tournament, display_name),
                    reply_markup=superadmin_tournament_close_kb.admin_repair_add_new_confirmation_keyboard(
                        tournament_id=callback_data.tournament_id
                    ),
                )
            return
        if (
            callback_data.action
            == superadmin_tournament_close_kb.AdminTournamentRepairAction.CREATE_NEW
        ):
            data = await state.get_data()
            await result_service.add_new_player_to_tournament(
                admin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
                display_name=str(data.get("repair_new_display_name", "")),
            )
            await state.clear()
            await callback.answer("Игрок добавлен.")
            if callback.message is not None:
                await _edit_repair_tournament_card(callback, callback_data.tournament_id)
            return
        if (
            callback_data.action
            == superadmin_tournament_close_kb.AdminTournamentRepairAction.EDIT_RESULTS
        ):
            results = await result_service.get_tournament_results(
                admin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
            )
            page = pagination_service.paginate(
                results.players,
                page=0,
                page_size=admin_results_kb.ADMIN_RESULT_PAGE_SIZE,
            )
            await state.update_data(
                result_return_context="superadmin_repair",
                repair_tournament_id=callback_data.tournament_id,
            )
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=result_fmt.players_table(results, page),
                    reply_markup=_repair_result_players_keyboard(results, page),
                    parse_mode=RESULT_SUMMARY_PARSE_MODE,
                )
            return
        if (
            callback_data.action
            == superadmin_tournament_close_kb.AdminTournamentRepairAction.PHOTOS
        ):
            results = await result_service.get_tournament_results(
                admin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
            )
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=result_fmt.photo_menu(results),
                    reply_markup=_repair_photo_menu_keyboard(results),
                )
            return
        if callback_data.action in _REPAIR_COMBINATION_ACTIONS:
            await _handle_repair_combination_action(callback, callback_data)
            return
        if callback_data.action in _REPAIR_PHOTO_ACTIONS:
            await _handle_repair_photo_action(callback, callback_data, state)
            return
    except AdminAccessDeniedError:
        await callback.answer(text.ACCESS_DENIED, show_alert=True)
        return
    except ResultDuplicateNameError:
        await callback.answer(
            "Такой игрок уже существует.\nИспользуй «Играл ранее».",
            show_alert=True,
        )
        return
    except ResultPlayerAlreadyAddedError:
        await callback.answer("Этот игрок уже добавлен в турнир.", show_alert=True)
        if callback.message is not None:
            await _edit_repair_tournament_card(callback, callback_data.tournament_id)
        return
    except ResultCombinationAlreadyExistsError:
        await callback.answer("Такая комбинация уже добавлена.", show_alert=True)
        return
    except ResultCombinationNotFoundError:
        await callback.answer("Комбинация не найдена.", show_alert=True)
        return
    except (ResultTournamentNotFoundError, ResultUserNotFoundError):
        await callback.answer(text.ADMIN_RESULTS_NOT_FOUND, show_alert=True)
        return
    except TournamentResultsEditingUnavailableError:
        await callback.answer("Турнир недоступен для редактирования.", show_alert=True)
        return
    await callback.answer(text.ADMIN_RESULTS_NOT_FOUND, show_alert=True)


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


async def _send_post_close_publication_preview(
    callback: CallbackQuery,
    tournament_id: int,
) -> None:
    if callback.message is None:
        return
    chat_id = callback.message.chat.id
    preview = await tournament_publication_service.get_result_publication_content_preview(
        callback.from_user.id,
        tournament_id,
    )
    report = publication_fmt.result_publication_report(preview)
    try:
        await _send_publication_media(
            callback.bot,
            chat_id=chat_id,
            photos=preview.photos,
            report=report,
        )
    except TelegramAPIError:
        logger.exception("Failed to send post-close tournament result preview")
    await callback.message.answer(
        "Турнир закрыт ✅",
        reply_markup=superadmin_tournament_close_kb.admin_publish_results_action_keyboard(
            tournament_id
        ),
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


async def _handle_repair_photo_action(
    callback: CallbackQuery,
    callback_data: superadmin_tournament_close_kb.AdminTournamentRepairCallback,
    state: FSMContext,
) -> None:
    action = callback_data.action
    tournament_id = callback_data.tournament_id
    if action == superadmin_tournament_close_kb.AdminTournamentRepairAction.ADD_PHOTO:
        await state.set_state(AdminResultStates.collecting_repair_tournament_photos)
        await state.update_data(repair_photo_tournament_id=tournament_id)
        photo_count = await result_service.count_tournament_photos(
            admin_telegram_id=callback.from_user.id,
            tournament_id=tournament_id,
        )
        await callback.answer()
        if callback.message is not None:
            await _delete_callback_message(callback)
            await send_photo_control_message(
                callback.message,
                state,
                _repair_photo_control_context(tournament_id),
                photo_count=photo_count,
            )
        return

    if action == superadmin_tournament_close_kb.AdminTournamentRepairAction.PHOTO_DONE:
        await state.clear()
        results = await result_service.get_tournament_results(
            admin_telegram_id=callback.from_user.id,
            tournament_id=tournament_id,
        )
        await callback.answer()
        if callback.message is not None:
            await edit_message_if_changed(
                callback.message,
                text=result_fmt.photo_menu(results),
                reply_markup=_repair_photo_menu_keyboard(results),
            )
        return

    if action == superadmin_tournament_close_kb.AdminTournamentRepairAction.VIEW_PHOTOS:
        if callback.message is not None:
            await state.update_data(repair_photo_control_message_id=callback.message.message_id)
        await _send_tournament_photos(
            callback=callback,
            tournament_id=tournament_id,
            state=state,
            context=_repair_photo_control_context(tournament_id),
            restore_control=lambda: _restore_repair_photo_menu_control(callback, tournament_id),
        )
        return

    if action == superadmin_tournament_close_kb.AdminTournamentRepairAction.DELETE_PHOTOS_CONFIRM:
        await callback.answer()
        if callback.message is not None:
            await edit_message_if_changed(
                callback.message,
                text=result_fmt.delete_photos_confirmation(),
                reply_markup=admin_results_kb.admin_result_delete_photos_confirmation_keyboard(
                    tournament_id,
                    back_callback=superadmin_tournament_close_kb.AdminTournamentRepairCallback(
                        action=superadmin_tournament_close_kb.AdminTournamentRepairAction.PHOTOS,
                        tournament_id=tournament_id,
                    ),
                    cancel_callback=superadmin_tournament_close_kb.AdminTournamentRepairCallback(
                        action=superadmin_tournament_close_kb.AdminTournamentRepairAction.CANCEL,
                        tournament_id=tournament_id,
                    ),
                ),
            )
        return

    results = await result_service.delete_tournament_photos(
        admin_telegram_id=callback.from_user.id,
        tournament_id=tournament_id,
    )
    await callback.answer("Фото удалены.")
    if callback.message is not None:
        await edit_message_if_changed(
            callback.message,
            text=result_fmt.photo_menu(results),
            reply_markup=_repair_photo_menu_keyboard(results),
        )


async def _handle_repair_combination_action(
    callback: CallbackQuery,
    callback_data: superadmin_tournament_close_kb.AdminTournamentRepairCallback,
) -> None:
    action = callback_data.action
    if action == superadmin_tournament_close_kb.AdminTournamentRepairAction.COMBINATIONS:
        combinations = await result_service.get_tournament_combinations(
            admin_telegram_id=callback.from_user.id,
            tournament_id=callback_data.tournament_id,
        )
        await callback.answer()
        if callback.message is not None:
            await edit_message_if_changed(
                callback.message,
                text=result_fmt.combinations_root(combinations),
                reply_markup=superadmin_tournament_close_kb.admin_repair_combination_root_keyboard(
                    combinations
                ),
            )
        return

    if action == superadmin_tournament_close_kb.AdminTournamentRepairAction.ADD_COMBINATION:
        combinations = await result_service.get_tournament_combinations(
            admin_telegram_id=callback.from_user.id,
            tournament_id=callback_data.tournament_id,
        )
        await callback.answer()
        if callback.message is not None:
            await edit_message_if_changed(
                callback.message,
                text=result_fmt.combination_player_prompt(combinations),
                reply_markup=superadmin_tournament_close_kb.admin_repair_combination_players_keyboard(
                    combinations
                ),
            )
        return

    if (
        action
        == superadmin_tournament_close_kb.AdminTournamentRepairAction.SELECT_COMBINATION_PLAYER
    ):
        combinations = await result_service.get_tournament_combinations(
            admin_telegram_id=callback.from_user.id,
            tournament_id=callback_data.tournament_id,
        )
        player = next(
            (item for item in combinations.players if item.player_id == callback_data.player_id),
            None,
        )
        if player is None:
            await callback.answer(text.ADMIN_RESULTS_NOT_FOUND, show_alert=True)
            return
        await callback.answer()
        if callback.message is not None:
            await edit_message_if_changed(
                callback.message,
                text=result_fmt.combination_type_prompt(player.display_name),
                reply_markup=superadmin_tournament_close_kb.admin_repair_combination_types_keyboard(
                    tournament_id=callback_data.tournament_id,
                    player_id=callback_data.player_id,
                ),
            )
        return

    if action == superadmin_tournament_close_kb.AdminTournamentRepairAction.SAVE_COMBINATION:
        combinations = await result_service.add_tournament_combination(
            admin_telegram_id=callback.from_user.id,
            tournament_id=callback_data.tournament_id,
            player_id=callback_data.player_id,
            combination_type=TournamentCombinationType(callback_data.combination_type),
        )
        await callback.answer("Комбинация добавлена.")
        if callback.message is not None:
            await edit_message_if_changed(
                callback.message,
                text=result_fmt.combinations_root(combinations),
                reply_markup=superadmin_tournament_close_kb.admin_repair_combination_root_keyboard(
                    combinations
                ),
            )
        return

    if action == superadmin_tournament_close_kb.AdminTournamentRepairAction.DELETE_COMBINATION_MENU:
        combinations = await result_service.get_tournament_combinations(
            admin_telegram_id=callback.from_user.id,
            tournament_id=callback_data.tournament_id,
        )
        await callback.answer()
        if callback.message is not None:
            await edit_message_if_changed(
                callback.message,
                text=result_fmt.combination_delete_prompt(combinations),
                reply_markup=superadmin_tournament_close_kb.admin_repair_combination_delete_keyboard(
                    combinations
                ),
            )
        return

    combinations = await result_service.delete_tournament_combination(
        admin_telegram_id=callback.from_user.id,
        tournament_id=callback_data.tournament_id,
        combination_id=callback_data.combination_id,
    )
    await callback.answer("Комбинация удалена.")
    if callback.message is not None:
        await edit_message_if_changed(
            callback.message,
            text=result_fmt.combinations_root(combinations),
            reply_markup=superadmin_tournament_close_kb.admin_repair_combination_root_keyboard(
                combinations
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
        players = await result_service.search_closed_result_replacement_users(
            superadmin_telegram_id=message.from_user.id,
            tournament_id=tournament_id,
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


@router.message(AdminResultStates.entering_repair_existing_player_search)
async def enter_repair_existing_player_search(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return
    data = await state.get_data()
    tournament_id = int(data["repair_tournament_id"])
    try:
        players = await result_service.search_existing_users_for_tournament(
            admin_telegram_id=message.from_user.id,
            tournament_id=tournament_id,
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
    except TournamentResultsEditingUnavailableError:
        await state.clear()
        await message.answer("Турнир недоступен для редактирования.")
        return

    if not players:
        await message.answer("Игроки не найдены.")
        return
    await message.answer(
        "Нашел игроков в базе:",
        reply_markup=superadmin_tournament_close_kb.admin_repair_search_results_keyboard(
            tournament_id=tournament_id,
            players=players,
        ),
    )


@router.message(AdminResultStates.entering_repair_new_player)
async def enter_repair_new_player(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return
    data = await state.get_data()
    tournament_id = int(data["repair_tournament_id"])
    display_name = message.text or ""
    try:
        tournament, display_name = await result_service.get_new_player_add_confirmation(
            admin_telegram_id=message.from_user.id,
            tournament_id=tournament_id,
            display_name=display_name,
        )
    except AdminAccessDeniedError:
        await state.clear()
        await message.answer(text.ACCESS_DENIED)
        return
    except ResultDuplicateNameError:
        await message.answer("Такой игрок уже существует.\nИспользуй «Играл ранее».")
        return
    except TournamentResultsEditingUnavailableError:
        await state.clear()
        await message.answer("Турнир недоступен для редактирования.")
        return
    except (ResultTournamentNotFoundError, ValueError):
        await message.answer("Введи корректное имя игрока.")
        return

    await state.set_state(AdminResultStates.confirming_repair_new_player)
    await state.update_data(
        repair_tournament_id=tournament_id,
        repair_new_display_name=display_name,
    )
    await message.answer(
        result_fmt.add_new_player_prompt(tournament, display_name),
        reply_markup=superadmin_tournament_close_kb.admin_repair_add_new_confirmation_keyboard(
            tournament_id=tournament_id
        ),
    )


@router.message(AdminResultStates.collecting_repair_tournament_photos, F.photo)
async def collect_repair_tournament_photo(message: Message, state: FSMContext) -> None:
    if message.from_user is None or not message.photo:
        return
    data = await state.get_data()
    tournament_id = int(data["repair_photo_tournament_id"])
    photo = message.photo[-1]
    try:
        result = await result_service.add_tournament_photo(
            admin_telegram_id=message.from_user.id,
            tournament_id=tournament_id,
            telegram_file_id=photo.file_id,
            telegram_file_unique_id=photo.file_unique_id,
        )
    except AdminAccessDeniedError:
        await state.clear()
        await message.answer(text.ACCESS_DENIED)
        return
    except ResultTournamentNotFoundError:
        await state.clear()
        await message.answer(text.ADMIN_RESULTS_NOT_FOUND)
        return
    except TournamentResultsEditingUnavailableError:
        await state.clear()
        await message.answer("Турнир недоступен для редактирования.")
        return
    context = _repair_photo_control_context(tournament_id)
    if message.media_group_id:
        schedule_album_photo_control_refresh(
            message,
            state,
            context,
            count_provider=lambda: result_service.count_tournament_photos(
                admin_telegram_id=message.from_user.id,
                tournament_id=tournament_id,
            ),
            limit_reached=result.limit_reached,
        )
        return
    await refresh_photo_control_message(
        message,
        state,
        context,
        photo_count=result.photo_count,
        limit_reached=result.limit_reached,
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


async def _edit_repair_tournament_card(
    callback: CallbackQuery,
    tournament_id: int,
) -> None:
    if callback.message is None:
        return
    readiness = await result_service.get_close_readiness(
        superadmin_telegram_id=callback.from_user.id,
        tournament_id=tournament_id,
    )
    await edit_message_if_changed(
        callback.message,
        text=result_fmt.correction_tournament_card(readiness),
        reply_markup=superadmin_tournament_close_kb.admin_correction_tournament_card_keyboard(
            readiness
        ),
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


async def _edit_closed_correction_card(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    tournament_id: int,
    page: int,
) -> None:
    results = await result_service.get_closed_tournament_results(
        superadmin_telegram_id=callback.from_user.id,
        tournament_id=tournament_id,
    )
    await state.update_data(
        **{
            f"closed_correction_snapshot_{tournament_id}": ResultService.snapshot_to_payload(
                ResultService.snapshot_from_results(results)
            )
        }
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


async def _edit_closed_result_player_detail(
    *,
    callback: CallbackQuery,
    tournament_id: int,
    page: int,
    player_id: int,
) -> None:
    results = await result_service.get_closed_tournament_results(
        superadmin_telegram_id=callback.from_user.id,
        tournament_id=tournament_id,
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


async def _list_closed_tournaments_or_empty(superadmin_telegram_id: int) -> list[object]:
    list_closed = getattr(result_service, "list_closed_tournaments_for_superadmin", None)
    if list_closed is None:
        return []
    return await list_closed(superadmin_telegram_id)


def _repair_result_players_keyboard(results: object, page: object) -> object:
    tournament_id = results.tournament.id
    return admin_results_kb.admin_result_players_keyboard(
        results,
        page,
        back_callback=superadmin_tournament_close_kb.AdminTournamentRepairCallback(
            action=superadmin_tournament_close_kb.AdminTournamentRepairAction.OPEN,
            tournament_id=tournament_id,
        ),
        cancel_callback=superadmin_tournament_close_kb.AdminTournamentRepairCallback(
            action=superadmin_tournament_close_kb.AdminTournamentRepairAction.CANCEL,
            tournament_id=tournament_id,
        ),
    )


def _repair_photo_menu_keyboard(results: object) -> object:
    tournament_id = results.tournament.id
    return admin_results_kb.admin_result_photo_menu_keyboard(
        results,
        add_callback=superadmin_tournament_close_kb.AdminTournamentRepairCallback(
            action=superadmin_tournament_close_kb.AdminTournamentRepairAction.ADD_PHOTO,
            tournament_id=tournament_id,
        ),
        view_callback=superadmin_tournament_close_kb.AdminTournamentRepairCallback(
            action=superadmin_tournament_close_kb.AdminTournamentRepairAction.VIEW_PHOTOS,
            tournament_id=tournament_id,
        ),
        delete_callback=superadmin_tournament_close_kb.AdminTournamentRepairCallback(
            action=superadmin_tournament_close_kb.AdminTournamentRepairAction.DELETE_PHOTOS_CONFIRM,
            tournament_id=tournament_id,
        ),
        back_callback=superadmin_tournament_close_kb.AdminTournamentRepairCallback(
            action=superadmin_tournament_close_kb.AdminTournamentRepairAction.OPEN,
            tournament_id=tournament_id,
        ),
        cancel_callback=superadmin_tournament_close_kb.AdminTournamentRepairCallback(
            action=superadmin_tournament_close_kb.AdminTournamentRepairAction.CANCEL,
            tournament_id=tournament_id,
        ),
    )


def _repair_photo_control_context(tournament_id: int) -> PhotoControlContext:
    return PhotoControlContext(
        tournament_id=tournament_id,
        control_message_id_key="repair_photo_control_message_id",
        reply_markup=superadmin_tournament_close_kb.admin_repair_photo_collect_keyboard(
            tournament_id
        ),
    )


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
    closed_tournaments = await _list_closed_tournaments_or_empty(callback.from_user.id)
    ready = [item for item in tournaments if item.is_ready]
    problematic = [item for item in tournaments if not item.is_ready]
    await state.clear()
    await callback.answer()
    if callback.message is None:
        return
    if not ready and not problematic and not closed_tournaments:
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
            has_correction_targets=bool(tournaments),
            has_closed_correction_targets=bool(closed_tournaments),
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
    state: FSMContext | None = None,
    context: PhotoControlContext | None = None,
    restore_control: Callable[[], Awaitable[int | None]] | None = None,
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
    if state is not None and context is not None and restore_control is not None:
        await send_media_then_restore_control(
            callback.message,
            state,
            context,
            media_sender=lambda: _send_photo_media(callback.message, photos),
            restore_control=restore_control,
        )
        return
    await _send_photo_media(callback.message, photos)


async def _send_photo_media(message: Message, photos: list[object]) -> None:
    if len(photos) == 1:
        await message.answer_photo(photos[0].telegram_file_id)
        return
    await message.answer_media_group(
        [InputMediaPhoto(media=photo.telegram_file_id) for photo in photos]
    )


async def _restore_repair_photo_menu_control(
    callback: CallbackQuery,
    tournament_id: int,
) -> int | None:
    if callback.message is None:
        return None
    results = await result_service.get_tournament_results(
        admin_telegram_id=callback.from_user.id,
        tournament_id=tournament_id,
    )
    sent = await callback.message.answer(
        result_fmt.photo_menu(results),
        reply_markup=_repair_photo_menu_keyboard(results),
    )
    return sent.message_id


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
