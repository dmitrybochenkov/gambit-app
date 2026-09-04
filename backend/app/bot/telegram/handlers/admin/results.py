import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InputMediaPhoto, Message

from app.bot.telegram.formatters import results as result_fmt
from app.bot.telegram.handlers.admin.shared import (
    RESULT_SUMMARY_PARSE_MODE,
    parse_result_manual_value,
    result_field_name,
    to_result_field,
)
from app.bot.telegram.handlers.admin.shared import (
    delete_callback_message as _delete_callback_message,
)
from app.bot.telegram.handlers.admin.shared import (
    delete_message_by_id as _delete_message_by_id,
)
from app.bot.telegram.handlers.superadmin.navigation import send_superadmin_panel
from app.bot.telegram.keyboards import labels
from app.bot.telegram.keyboards.admin import panel as admin_panel_kb
from app.bot.telegram.keyboards.admin import results as admin_results_kb
from app.bot.telegram.message_edit import edit_message_if_changed
from app.bot.telegram.photo_collection import (
    PhotoControlContext,
    refresh_photo_control_message,
    schedule_album_photo_control_refresh,
    send_media_then_restore_control,
    send_photo_control_message,
)
from app.bot.telegram.states import AdminResultStates
from app.bot.telegram.texts.admin import panel as panel_text
from app.bot.telegram.texts.admin import results as result_text
from app.db.models.enums import TournamentCombinationType
from app.services.access_policy import AdminAccessDeniedError
from app.services.pagination import pagination_service
from app.services.result_service import (
    ResultCombinationAlreadyExistsError,
    ResultCombinationNotFoundError,
    ResultInvalidPlayerDataError,
    ResultService,
    ResultTournamentNotFoundError,
    ResultUserNotFoundError,
    ResultValidationError,
    TournamentResultsEditingUnavailableError,
    result_service,
)
from app.services.tournament_check_in_service import (
    TournamentCheckInClosedError,
    TournamentCheckInNotFoundError,
    TournamentCheckInUserNotFoundError,
)
from app.services.tournament_combination_service import tournament_combination_service
from app.services.tournament_photo_service import tournament_photo_service
from app.services.user_access_service import user_access_service

logger = logging.getLogger(__name__)


router = Router(name="admin.results")


@router.callback_query(admin_results_kb.AdminResultBackToMenuCallback.filter())
async def back_to_admin_from_results(callback: CallbackQuery) -> None:
    try:
        admin_panel = await user_access_service.get_admin_panel_for_admin(callback.from_user.id)
    except AdminAccessDeniedError:
        await callback.answer(panel_text.ACCESS_DENIED, show_alert=True)
        return

    await callback.answer()
    if callback.message is not None:
        await _delete_callback_message(callback)
        await callback.message.answer(
            panel_text.ADMIN_PANEL_WELCOME,
            reply_markup=admin_panel_kb.admin_panel_keyboard(admin_panel.admin),
        )


@router.message(F.text == labels.ADMIN_PANEL_RESULTS)
async def show_result_tournaments(message: Message) -> None:
    if message.from_user is None:
        return

    try:
        tournaments = await result_service.list_editable_tournaments(message.from_user.id)
    except AdminAccessDeniedError:
        await message.answer(panel_text.ACCESS_DENIED)
        return
    if not tournaments:
        await message.answer(
            "На сегодня нет активного турнира.",
            reply_markup=admin_results_kb.admin_result_root_no_today_keyboard(),
        )
        return

    if len(tournaments) > 1:
        page = pagination_service.paginate(
            tournaments,
            page=0,
            page_size=admin_results_kb.ADMIN_RESULT_PAGE_SIZE,
        )
        await message.answer(
            result_fmt.tournament_list(page),
            reply_markup=admin_results_kb.admin_result_tournament_list_keyboard(page),
        )
        return

    try:
        results = await result_service.get_tournament_results(
            admin_telegram_id=message.from_user.id,
            tournament_id=tournaments[0].id,
        )
    except TournamentResultsEditingUnavailableError:
        await message.answer(result_text.ADMIN_RESULTS_EDITING_UNAVAILABLE)
        return

    await message.answer(
        result_fmt.management_root(results),
        reply_markup=admin_results_kb.admin_result_root_keyboard(results),
        parse_mode=RESULT_SUMMARY_PARSE_MODE,
    )


@router.callback_query(admin_results_kb.AdminResultTournamentCallback.filter())
async def select_result_tournament_action(
    callback: CallbackQuery,
    callback_data: admin_results_kb.AdminResultTournamentCallback,
) -> None:
    try:
        if callback_data.action == admin_results_kb.AdminResultTournamentAction.CANCEL:
            await callback.answer(result_text.ADMIN_RESULTS_CANCELLED)
            await _return_to_admin_menu(callback, result_text.ADMIN_RESULTS_CANCELLED)
            return
        if callback_data.action == admin_results_kb.AdminResultTournamentAction.PAGE:
            tournaments = await result_service.list_editable_tournaments(callback.from_user.id)
            page = pagination_service.paginate(
                tournaments,
                page=callback_data.page,
                page_size=admin_results_kb.ADMIN_RESULT_PAGE_SIZE,
            )
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=result_fmt.tournament_list(page),
                    reply_markup=admin_results_kb.admin_result_tournament_list_keyboard(page),
                )
            return
        if callback_data.action == admin_results_kb.AdminResultTournamentAction.OPEN:
            results = await result_service.get_tournament_results(
                admin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
            )
            await callback.answer()
            await _show_result_root_from_callback(callback, results)
            return
    except AdminAccessDeniedError:
        await callback.answer(panel_text.ACCESS_DENIED, show_alert=True)
        return
    except (ResultTournamentNotFoundError, TournamentResultsEditingUnavailableError):
        await callback.answer(result_text.ADMIN_RESULTS_NOT_FOUND, show_alert=True)
        return
    await callback.answer(result_text.ADMIN_RESULTS_NOT_FOUND, show_alert=True)


@router.callback_query(admin_results_kb.AdminResultMenuCallback.filter())
async def select_result_menu_action(
    callback: CallbackQuery,
    callback_data: admin_results_kb.AdminResultMenuCallback,
    state: FSMContext,
) -> None:
    try:
        if callback_data.action == admin_results_kb.AdminResultMenuAction.CANCEL:
            await state.clear()
            await callback.answer(result_text.ADMIN_RESULTS_CANCELLED)
            await _return_to_admin_menu(callback, result_text.ADMIN_RESULTS_CANCELLED)
            return
        results = await result_service.get_tournament_results(
            admin_telegram_id=callback.from_user.id,
            tournament_id=callback_data.tournament_id,
        )
        await callback.answer()
        if callback_data.action == admin_results_kb.AdminResultMenuAction.ROOT:
            await _show_result_root_from_callback(callback, results)
            return
        if callback_data.action == admin_results_kb.AdminResultMenuAction.DATA:
            await _show_results_screen_from_callback(callback, results, state)
            return
        if callback_data.action == admin_results_kb.AdminResultMenuAction.PHOTOS:
            await _show_photo_menu_from_callback(callback, results)
            return
        if callback_data.action == admin_results_kb.AdminResultMenuAction.COMBINATIONS:
            combinations = await tournament_combination_service.list_for_tournament(
                admin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
            )
            await _show_combinations_from_callback(callback, combinations)
            return
    except AdminAccessDeniedError:
        await callback.answer(panel_text.ACCESS_DENIED, show_alert=True)
        return
    except ResultTournamentNotFoundError:
        await callback.answer(result_text.ADMIN_RESULTS_NOT_FOUND, show_alert=True)
        return
    await callback.answer(result_text.ADMIN_RESULTS_NOT_FOUND, show_alert=True)


@router.callback_query(admin_results_kb.AdminCombinationCallback.filter())
async def select_combination_action(
    callback: CallbackQuery,
    callback_data: admin_results_kb.AdminCombinationCallback,
    state: FSMContext,
) -> None:
    try:
        if callback_data.action == admin_results_kb.AdminCombinationAction.CANCEL:
            await state.clear()
            await callback.answer(result_text.ADMIN_RESULTS_CANCELLED)
            await _return_to_admin_menu(callback, result_text.ADMIN_RESULTS_CANCELLED)
            return
        if callback_data.action == admin_results_kb.AdminCombinationAction.BACK:
            combinations = await tournament_combination_service.list_for_tournament(
                admin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
            )
            await callback.answer()
            await _show_combinations_from_callback(callback, combinations)
            return
        if callback_data.action == admin_results_kb.AdminCombinationAction.ADD:
            combinations = await tournament_combination_service.list_for_tournament(
                admin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
            )
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=result_fmt.combination_player_prompt(combinations),
                    reply_markup=admin_results_kb.admin_combination_players_keyboard(combinations),
                )
            return
        if callback_data.action == admin_results_kb.AdminCombinationAction.SELECT_PLAYER:
            combinations = await tournament_combination_service.list_for_tournament(
                admin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
            )
            player = next(
                (
                    item
                    for item in combinations.players
                    if item.player_id == callback_data.player_id
                ),
                None,
            )
            if player is None:
                await callback.answer(result_text.PLAYER_NOT_FOUND, show_alert=True)
                return
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=result_fmt.combination_type_prompt(player.display_name),
                    reply_markup=admin_results_kb.admin_combination_types_keyboard(
                        tournament_id=callback_data.tournament_id,
                        player_id=callback_data.player_id,
                    ),
                )
            return
        if callback_data.action == admin_results_kb.AdminCombinationAction.SELECT_RANK:
            combinations = await tournament_combination_service.list_for_tournament(
                admin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
            )
            player = next(
                (
                    item
                    for item in combinations.players
                    if item.player_id == callback_data.player_id
                ),
                None,
            )
            if player is None:
                await callback.answer(result_text.PLAYER_NOT_FOUND, show_alert=True)
                return

            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=result_fmt.four_of_a_kind_rank_prompt(player.display_name),
                    reply_markup=admin_results_kb.admin_four_of_a_kind_rank_keyboard(
                        tournament_id=callback_data.tournament_id,
                        player_id=callback_data.player_id,
                    ),
                )
            return
        if callback_data.action == admin_results_kb.AdminCombinationAction.SAVE:
            combinations = await tournament_combination_service.add_combination(
                admin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
                player_id=callback_data.player_id,
                combination_type=TournamentCombinationType(callback_data.combination_type),
                rank=callback_data.rank or None,
            )
            await callback.answer("Комбинация добавлена.")
            await _show_combinations_from_callback(callback, combinations)
            return
        if callback_data.action == admin_results_kb.AdminCombinationAction.DELETE_MENU:
            combinations = await tournament_combination_service.list_for_tournament(
                admin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
            )
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=result_fmt.combination_delete_prompt(combinations),
                    reply_markup=admin_results_kb.admin_combination_delete_keyboard(combinations),
                )
            return
        if callback_data.action == admin_results_kb.AdminCombinationAction.DELETE:
            combinations = await tournament_combination_service.delete_combination(
                admin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
                combination_id=callback_data.combination_id,
            )
            await callback.answer("Комбинация удалена.")
            await _show_combinations_from_callback(callback, combinations)
            return
    except AdminAccessDeniedError:
        await callback.answer(panel_text.ACCESS_DENIED, show_alert=True)
        return
    except ResultCombinationAlreadyExistsError:
        await callback.answer("Такая комбинация уже добавлена.", show_alert=True)
        return
    except ResultCombinationNotFoundError:
        await callback.answer("Комбинация не найдена.", show_alert=True)
        return
    except TournamentResultsEditingUnavailableError:
        await callback.answer(result_text.ADMIN_RESULTS_EDITING_UNAVAILABLE, show_alert=True)
        return
    except (ResultTournamentNotFoundError, ResultUserNotFoundError, ValueError):
        await callback.answer(result_text.ADMIN_RESULTS_NOT_FOUND, show_alert=True)
        return
    await callback.answer(result_text.ADMIN_RESULTS_NOT_FOUND, show_alert=True)


@router.callback_query(admin_results_kb.AdminResultPlayerCallback.filter())
async def select_result_player(
    callback: CallbackQuery,
    callback_data: admin_results_kb.AdminResultPlayerCallback,
    state: FSMContext,
) -> None:
    try:
        if callback_data.action == admin_results_kb.AdminResultPlayerAction.CANCEL:
            await state.clear()
            await callback.answer(result_text.ADMIN_RESULTS_CANCELLED)
            await _return_from_result_cancel(callback, result_text.ADMIN_RESULTS_CANCELLED)
            return

        results = await result_service.get_tournament_results(
            admin_telegram_id=callback.from_user.id,
            tournament_id=callback_data.tournament_id,
        )
        page = pagination_service.paginate(
            results.players,
            page=callback_data.page,
            page_size=admin_results_kb.ADMIN_RESULT_PAGE_SIZE,
        )
        if callback_data.action == admin_results_kb.AdminResultPlayerAction.PAGE:
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=result_fmt.players_table(results, page),
                    reply_markup=await _admin_result_players_keyboard(results, page, state),
                    parse_mode=RESULT_SUMMARY_PARSE_MODE,
                )
            return
        if callback_data.action == admin_results_kb.AdminResultPlayerAction.ADD_PHOTO:
            await state.set_state(AdminResultStates.collecting_tournament_photos)
            await state.update_data(result_photo_tournament_id=callback_data.tournament_id)
            photo_count = await tournament_photo_service.count_for_tournament(
                admin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
            )
            await callback.answer()
            if callback.message is not None:
                await _delete_callback_message(callback)
                await send_photo_control_message(
                    callback.message,
                    state,
                    _admin_photo_control_context(callback_data.tournament_id),
                    photo_count=photo_count,
                )
            return
        if callback_data.action == admin_results_kb.AdminResultPlayerAction.VIEW_PHOTOS:
            if callback.message is not None:
                await state.update_data(
                    result_photo_control_message_id=callback.message.message_id,
                )
            await _send_tournament_photos(
                callback,
                state,
                callback_data.tournament_id,
                _admin_photo_control_context(callback_data.tournament_id),
            )
            return
        if callback_data.action == admin_results_kb.AdminResultPlayerAction.DELETE_PHOTOS:
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=result_fmt.delete_photos_confirmation(),
                    reply_markup=admin_results_kb.admin_result_delete_photos_confirmation_keyboard(
                        callback_data.tournament_id,
                        back_callback=admin_results_kb.AdminResultPhotoCallback(
                            action=admin_results_kb.AdminResultPhotoAction.BACK,
                            tournament_id=callback_data.tournament_id,
                        ),
                    ),
                )
            return
        player = ResultService.find_result_player(results, callback_data.player_id)
        if player is None:
            await callback.answer(result_text.PLAYER_NOT_FOUND, show_alert=True)
            return
    except AdminAccessDeniedError:
        await callback.answer(panel_text.ACCESS_DENIED, show_alert=True)
        return
    except (ResultTournamentNotFoundError, TournamentCheckInClosedError):
        await callback.answer(result_text.ADMIN_RESULTS_NOT_FOUND, show_alert=True)
        return
    except TournamentResultsEditingUnavailableError:
        await callback.answer(result_text.ADMIN_RESULTS_EDITING_UNAVAILABLE, show_alert=True)
        return
    except (TournamentCheckInUserNotFoundError, TournamentCheckInNotFoundError):
        await callback.answer(result_text.PLAYER_NOT_FOUND, show_alert=True)
        return
    except ResultValidationError as error:
        await callback.answer()
        if callback.message is not None:
            await callback.message.answer(result_text.admin_result_check_failed(error.errors))
        return

    await state.clear()

    await callback.answer()
    if callback.message is not None:
        await _delete_callback_message(callback)
        await callback.message.answer(
            result_fmt.player_detail(results, player),
            reply_markup=await _admin_result_player_fields_keyboard(
                results,
                player,
                callback_data.page,
                state,
            ),
        )


@router.callback_query(admin_results_kb.AdminResultFieldCallback.filter())
async def select_result_field(
    callback: CallbackQuery,
    callback_data: admin_results_kb.AdminResultFieldCallback,
    state: FSMContext,
) -> None:
    try:
        results = await result_service.get_tournament_results(
            admin_telegram_id=callback.from_user.id,
            tournament_id=callback_data.tournament_id,
        )
        player = ResultService.find_result_player(results, callback_data.player_id)
        if player is None:
            await callback.answer(result_text.PLAYER_NOT_FOUND, show_alert=True)
            return

        if callback_data.action == admin_results_kb.AdminResultFieldAction.CANCEL:
            await state.clear()
            await callback.answer(result_text.ADMIN_RESULTS_CANCELLED)
            await _return_from_result_cancel(callback, result_text.ADMIN_RESULTS_CANCELLED)
            return

        await state.clear()

        if callback_data.field == admin_results_kb.AdminResultField.BONUS:
            await state.set_state(AdminResultStates.entering_manual_value)
            await state.update_data(
                result_tournament_id=callback_data.tournament_id,
                result_player_id=callback_data.player_id,
                result_page=callback_data.page,
                result_field=callback_data.field.value,
                result_bonus_label=results.bonus_points_label,
                result_prompt_message_id=callback.message.message_id
                if callback.message is not None
                else 0,
            )
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=result_text.admin_results_manual_value_prompt(
                        callback_data.field.value,
                        bonus_label=results.bonus_points_label,
                    ),
                    reply_markup=admin_results_kb.admin_result_manual_value_keyboard(
                        tournament_id=callback_data.tournament_id,
                        page=callback_data.page,
                        player_id=callback_data.player_id,
                        field=callback_data.field,
                    ),
                )
            return

        await callback.answer()

        if callback.message is not None:
            await edit_message_if_changed(
                callback.message,
                text=result_fmt.field_prompt(
                    player,
                    result_field_name(callback_data.field, results),
                ),
                reply_markup=admin_results_kb.admin_result_value_keyboard(
                    tournament_id=callback_data.tournament_id,
                    page=callback_data.page,
                    player_id=callback_data.player_id,
                    field=callback_data.field,
                    occupied_places=ResultService.occupied_result_places(results),
                    current_place=player.place,
                ),
            )
    except AdminAccessDeniedError:
        await callback.answer(panel_text.ACCESS_DENIED, show_alert=True)
    except ResultTournamentNotFoundError:
        await callback.answer(result_text.ADMIN_RESULTS_NOT_FOUND, show_alert=True)
    except TournamentResultsEditingUnavailableError:
        await callback.answer(result_text.ADMIN_RESULTS_EDITING_UNAVAILABLE, show_alert=True)


@router.callback_query(admin_results_kb.AdminResultValueCallback.filter())
async def select_result_value(
    callback: CallbackQuery,
    callback_data: admin_results_kb.AdminResultValueCallback,
    state: FSMContext,
) -> None:
    try:
        if callback_data.action == admin_results_kb.AdminResultValueAction.CANCEL:
            await state.clear()
            await callback.answer(result_text.ADMIN_RESULTS_CANCELLED)
            await _return_from_result_cancel(
                callback,
                result_text.ADMIN_RESULTS_CANCELLED,
            )
            return

        service_field = to_result_field(callback_data.field)
        if callback_data.action == admin_results_kb.AdminResultValueAction.SET:
            results = await result_service.update_player_result_field(
                admin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
                player_id=callback_data.player_id,
                field=service_field,
                value=callback_data.value,
            )
            player = ResultService.find_result_player(results, callback_data.player_id)
            if player is None:
                await callback.answer(result_text.PLAYER_NOT_FOUND, show_alert=True)
                return
            await state.clear()
            await callback.answer(result_text.ADMIN_RESULTS_SAVED)
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=result_fmt.player_detail(results, player),
                    reply_markup=await _admin_result_player_fields_keyboard(
                        results,
                        player,
                        callback_data.page,
                        state,
                    ),
                )
            return

        results = await result_service.get_tournament_results(
            admin_telegram_id=callback.from_user.id,
            tournament_id=callback_data.tournament_id,
        )
        player = ResultService.find_result_player(results, callback_data.player_id)
        if player is None:
            await callback.answer(result_text.PLAYER_NOT_FOUND, show_alert=True)
            return

        if callback_data.action == admin_results_kb.AdminResultValueAction.BACK:
            await state.clear()
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=result_fmt.player_detail(results, player),
                    reply_markup=await _admin_result_player_fields_keyboard(
                        results,
                        player,
                        callback_data.page,
                        state,
                    ),
                )
            return

        if not ResultService.result_field_is_allowed(
            results.knockout_mode,
            service_field,
            results.supports_bonus_points,
        ):
            await callback.answer(result_text.ADMIN_RESULTS_NOT_FOUND, show_alert=True)
            return

        if callback_data.action == admin_results_kb.AdminResultValueAction.MANUAL:
            await state.set_state(AdminResultStates.entering_manual_value)
            await state.update_data(
                result_tournament_id=callback_data.tournament_id,
                result_player_id=callback_data.player_id,
                result_page=callback_data.page,
                result_field=callback_data.field.value,
                result_bonus_label=results.bonus_points_label,
                result_prompt_message_id=callback.message.message_id
                if callback.message is not None
                else 0,
            )
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=result_text.admin_results_manual_value_prompt(
                        callback_data.field.value,
                        bonus_label=results.bonus_points_label,
                    ),
                    reply_markup=admin_results_kb.admin_result_manual_value_keyboard(
                        tournament_id=callback_data.tournament_id,
                        page=callback_data.page,
                        player_id=callback_data.player_id,
                        field=callback_data.field,
                    ),
                )
            return
    except AdminAccessDeniedError:
        await callback.answer(panel_text.ACCESS_DENIED, show_alert=True)
    except ResultTournamentNotFoundError:
        await callback.answer(result_text.ADMIN_RESULTS_NOT_FOUND, show_alert=True)
    except TournamentResultsEditingUnavailableError:
        await callback.answer(result_text.ADMIN_RESULTS_EDITING_UNAVAILABLE, show_alert=True)
    except (ResultInvalidPlayerDataError, ResultUserNotFoundError, ValueError):
        await callback.answer(
            result_text.admin_results_invalid_manual_value(callback_data.field.value),
            show_alert=True,
        )


@router.callback_query(admin_results_kb.AdminResultPhotoCallback.filter())
async def select_result_photo_action(
    callback: CallbackQuery,
    callback_data: admin_results_kb.AdminResultPhotoCallback,
    state: FSMContext,
) -> None:
    try:
        if callback_data.action == admin_results_kb.AdminResultPhotoAction.CANCEL:
            await state.clear()
            await callback.answer(result_text.ADMIN_RESULTS_CANCELLED)
            await _return_to_admin_menu(callback, result_text.ADMIN_RESULTS_CANCELLED)
            return
        if callback_data.action == admin_results_kb.AdminResultPhotoAction.DONE:
            await state.clear()
            results = await result_service.get_tournament_results(
                admin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
            )
            await callback.answer()
            await _show_photo_menu_from_callback(callback, results)
            return
        if callback_data.action == admin_results_kb.AdminResultPhotoAction.BACK:
            results = await result_service.get_tournament_results(
                admin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
            )
            await callback.answer()
            await _show_photo_menu_from_callback(callback, results)
            return
        if callback_data.action == admin_results_kb.AdminResultPhotoAction.DELETE_ALL:
            await tournament_photo_service.delete_photos(
                admin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
            )
            results = await result_service.get_tournament_results(
                admin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
            )
            await state.clear()
            await callback.answer("Фото удалены.")
            await _show_photo_menu_from_callback(callback, results)
            return
    except AdminAccessDeniedError:
        await state.clear()
        await callback.answer(panel_text.ACCESS_DENIED, show_alert=True)
        return
    except ResultTournamentNotFoundError:
        await callback.answer(result_text.ADMIN_RESULTS_NOT_FOUND, show_alert=True)
        return
    except TournamentResultsEditingUnavailableError:
        await callback.answer(result_text.ADMIN_RESULTS_EDITING_UNAVAILABLE, show_alert=True)
        return
    await callback.answer(result_text.ADMIN_RESULTS_NOT_FOUND, show_alert=True)


@router.message(AdminResultStates.collecting_tournament_photos, F.photo)
async def collect_tournament_photo(message: Message, state: FSMContext) -> None:
    if message.from_user is None or not message.photo:
        return
    data = await state.get_data()
    tournament_id = int(data["result_photo_tournament_id"])
    photo = message.photo[-1]
    try:
        result = await tournament_photo_service.add_photo(
            admin_telegram_id=message.from_user.id,
            tournament_id=tournament_id,
            telegram_file_id=photo.file_id,
            telegram_file_unique_id=photo.file_unique_id,
        )
    except AdminAccessDeniedError:
        await state.clear()
        await message.answer(panel_text.ACCESS_DENIED)
        return
    except ResultTournamentNotFoundError:
        await state.clear()
        await message.answer(result_text.ADMIN_RESULTS_NOT_FOUND)
        return
    except TournamentResultsEditingUnavailableError:
        await state.clear()
        await message.answer(result_text.ADMIN_RESULTS_EDITING_UNAVAILABLE)
        return
    context = _admin_photo_control_context(tournament_id)
    if message.media_group_id:
        schedule_album_photo_control_refresh(
            message,
            state,
            context,
            count_provider=lambda: tournament_photo_service.count_for_tournament(
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


async def _show_results_screen_from_callback(
    callback: CallbackQuery,
    results: object,
    state: FSMContext,
) -> None:
    if callback.message is None:
        return
    page = pagination_service.paginate(
        results.players,
        page=0,
        page_size=admin_results_kb.ADMIN_RESULT_PAGE_SIZE,
    )
    await edit_message_if_changed(
        callback.message,
        text=result_fmt.players_table(results, page),
        reply_markup=await _admin_result_players_keyboard(results, page, state),
        parse_mode=RESULT_SUMMARY_PARSE_MODE,
    )


async def _show_result_root_from_callback(
    callback: CallbackQuery,
    results: object,
) -> None:
    if callback.message is None:
        return
    await edit_message_if_changed(
        callback.message,
        text=result_fmt.management_root(results),
        reply_markup=admin_results_kb.admin_result_root_keyboard(results),
        parse_mode=RESULT_SUMMARY_PARSE_MODE,
    )


async def _show_photo_menu_from_callback(
    callback: CallbackQuery,
    results: object,
) -> None:
    if callback.message is None:
        return
    await edit_message_if_changed(
        callback.message,
        text=result_fmt.photo_menu(results),
        reply_markup=_admin_result_photo_menu_keyboard(results),
    )


async def _show_combinations_from_callback(
    callback: CallbackQuery,
    combinations: object,
) -> None:
    if callback.message is None:
        return
    await edit_message_if_changed(
        callback.message,
        text=result_fmt.combinations_root(combinations),
        reply_markup=admin_results_kb.admin_combination_root_keyboard(combinations),
    )


async def _send_tournament_photos(
    callback: CallbackQuery,
    state: FSMContext,
    tournament_id: int,
    context: PhotoControlContext,
) -> None:
    try:
        photos = await tournament_photo_service.list_for_tournament(
            admin_telegram_id=callback.from_user.id,
            tournament_id=tournament_id,
        )
    except AdminAccessDeniedError:
        await callback.answer(panel_text.ACCESS_DENIED, show_alert=True)
        return
    except ResultTournamentNotFoundError:
        await callback.answer(result_text.ADMIN_RESULTS_NOT_FOUND, show_alert=True)
        return
    if not photos:
        await callback.answer("Фото турнира не добавлены.", show_alert=True)
        return
    await callback.answer()
    if callback.message is None:
        return
    await send_media_then_restore_control(
        callback.message,
        state,
        context,
        media_sender=lambda: _send_photo_media(callback.message, photos),
        restore_control=lambda: _restore_admin_photo_menu_control(callback, tournament_id),
    )


async def _send_photo_media(message: Message, photos: list[object]) -> None:
    if len(photos) == 1:
        await message.answer_photo(photos[0].telegram_file_id)
        return
    await message.answer_media_group(
        [InputMediaPhoto(media=photo.telegram_file_id) for photo in photos]
    )


async def _restore_admin_photo_menu_control(
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
        reply_markup=_admin_result_photo_menu_keyboard(results),
    )
    return sent.message_id


async def _admin_result_players_keyboard(
    results: object,
    page: object,
    state: FSMContext,
) -> object:
    return admin_results_kb.admin_result_players_keyboard(
        results,
        page,
        back_callback=admin_results_kb.AdminResultMenuCallback(
            action=admin_results_kb.AdminResultMenuAction.ROOT,
            tournament_id=results.tournament.id,
        ),
    )


async def _admin_result_player_fields_keyboard(
    results: object,
    player: object,
    page: int,
    state: FSMContext,
) -> object:
    return admin_results_kb.admin_result_player_fields_keyboard(
        results,
        player,
        page,
        back_callback=admin_results_kb.AdminResultPlayerCallback(
            action=admin_results_kb.AdminResultPlayerAction.PAGE,
            tournament_id=results.tournament.id,
            page=page,
            player_id=0,
        ),
    )


def _admin_result_photo_menu_keyboard(results: object) -> object:
    tournament_id = results.tournament.id
    return admin_results_kb.admin_result_photo_menu_keyboard(
        results,
        back_callback=admin_results_kb.AdminResultMenuCallback(
            action=admin_results_kb.AdminResultMenuAction.ROOT,
            tournament_id=tournament_id,
        ),
    )


def _admin_photo_control_context(tournament_id: int) -> PhotoControlContext:
    return PhotoControlContext(
        tournament_id=tournament_id,
        control_message_id_key="result_photo_control_message_id",
        reply_markup=admin_results_kb.admin_result_photo_collect_keyboard(tournament_id),
    )


async def _return_to_admin_menu(callback: CallbackQuery, message_text: str) -> None:
    if callback.message is None:
        return
    admin_panel = await user_access_service.get_admin_panel_for_admin(callback.from_user.id)
    await _delete_callback_message(callback)
    await callback.message.answer(
        message_text,
        reply_markup=admin_panel_kb.admin_panel_keyboard(admin_panel.admin),
    )


async def _return_from_result_cancel(
    callback: CallbackQuery,
    message_text: str,
    *,
    return_to_superadmin: bool = False,
) -> None:
    if callback.message is None:
        return
    if return_to_superadmin:
        await _delete_callback_message(callback)
        await send_superadmin_panel(
            callback.message,
            superadmin_telegram_id=callback.from_user.id,
            text=message_text,
        )
        return
    try:
        await _return_to_admin_menu(callback, message_text)
    except AdminAccessDeniedError:
        await _delete_callback_message(callback)
        await send_superadmin_panel(
            callback.message,
            superadmin_telegram_id=callback.from_user.id,
            text=message_text,
        )


@router.message(AdminResultStates.entering_manual_value)
async def enter_result_manual_value(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return

    data = await state.get_data()
    tournament_id = int(data["result_tournament_id"])
    player_id = int(data["result_player_id"])
    page_number = int(data.get("result_page", 0))
    field = admin_results_kb.AdminResultField(str(data["result_field"]))
    bonus_label = str(data.get("result_bonus_label") or "Бонус")
    try:
        value = parse_result_manual_value(
            message.text or "",
            field=field,
        )
        results = await result_service.update_player_result_field(
            admin_telegram_id=message.from_user.id,
            tournament_id=tournament_id,
            player_id=player_id,
            field=to_result_field(field),
            value=value,
        )
    except AdminAccessDeniedError:
        await state.clear()
        await message.answer(panel_text.ACCESS_DENIED)
        return
    except ResultTournamentNotFoundError:
        await state.clear()
        await message.answer(result_text.ADMIN_RESULTS_NOT_FOUND)
        return
    except TournamentResultsEditingUnavailableError:
        await state.clear()
        await message.answer(result_text.ADMIN_RESULTS_EDITING_UNAVAILABLE)
        return
    except (ResultInvalidPlayerDataError, ResultUserNotFoundError, ValueError):
        await message.answer(
            result_text.admin_results_invalid_manual_value(
                field.value,
                bonus_label=bonus_label,
            )
        )
        return

    player = ResultService.find_result_player(results, player_id)
    if player is None:
        await state.clear()
        await message.answer(result_text.PLAYER_NOT_FOUND)
        return
    reply_markup = await _admin_result_player_fields_keyboard(results, player, page_number, state)
    await state.clear()
    await _delete_message_by_id(
        message,
        int(data.get("result_prompt_message_id", 0)),
    )
    await message.answer(result_text.ADMIN_RESULTS_SAVED)
    await message.answer(
        result_fmt.player_detail(results, player),
        reply_markup=reply_markup,
    )
