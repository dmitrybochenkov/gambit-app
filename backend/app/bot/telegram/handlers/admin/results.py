# ruff: noqa: F403,F405
from aiogram import Router

from app.bot.telegram.handlers.admin.common import *  # noqa: F403

router = Router(name="admin.results")


@router.callback_query(keyboards.AdminResultBackToMenuCallback.filter())
async def back_to_admin_from_results(callback: CallbackQuery) -> None:
    try:
        admin_panel = await user_service.get_admin_panel_for_admin(callback.from_user.id)
    except AdminAccessDeniedError:
        await callback.answer(texts.admin.ACCESS_DENIED, show_alert=True)
        return

    await callback.answer()
    if callback.message is not None:
        await _delete_callback_message(callback)
        await callback.message.answer(
            texts.admin.ADMIN_PANEL_WELCOME,
            reply_markup=keyboards.admin_panel_keyboard(admin_panel.admin),
        )


@router.message(F.text == keyboards.ADMIN_PANEL_RESULTS)
async def show_result_tournaments(message: Message) -> None:
    if message.from_user is None:
        return

    try:
        results = await result_service.get_today_tournament_results(message.from_user.id)
    except AdminAccessDeniedError:
        await message.answer(texts.admin.ACCESS_DENIED)
        return
    except ResultTodayTournamentNotFoundError:
        await message.answer(
            "На сегодня нет активного турнира.",
            reply_markup=keyboards.admin_result_back_to_menu_keyboard(),
        )
        return
    except ResultTodayTournamentInvariantViolationError:
        await message.answer(
            "Не удалось определить сегодняшний турнир.\nОбратитесь к суперадминистратору."
        )
        return

    page = pagination_service.paginate(
        results.players,
        page=0,
        page_size=keyboards.ADMIN_RESULT_PAGE_SIZE,
    )
    await message.answer(
        format_admin_result_players(results, page),
        reply_markup=keyboards.admin_result_players_keyboard(results, page),
        parse_mode=RESULT_SUMMARY_PARSE_MODE,
    )


@router.callback_query(keyboards.AdminResultPlayerCallback.filter())
async def select_result_player(
    callback: CallbackQuery,
    callback_data: keyboards.AdminResultPlayerCallback,
    state: FSMContext,
) -> None:
    try:
        if callback_data.action == keyboards.AdminResultPlayerAction.CANCEL:
            await state.clear()
            await callback.answer(texts.admin.ADMIN_RESULTS_CANCELLED)
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer(texts.admin.ADMIN_RESULTS_CANCELLED)
            return

        results = await result_service.get_tournament_results(
            admin_telegram_id=callback.from_user.id,
            tournament_id=callback_data.tournament_id,
        )
        page = pagination_service.paginate(
            results.players,
            page=callback_data.page,
            page_size=keyboards.ADMIN_RESULT_PAGE_SIZE,
        )
        if callback_data.action == keyboards.AdminResultPlayerAction.BACK:
            await state.clear()
            await callback.answer()
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer(
                    format_admin_result_players(results, page),
                    reply_markup=keyboards.admin_result_players_keyboard(results, page),
                    parse_mode=RESULT_SUMMARY_PARSE_MODE,
                )
            return

        if callback_data.action == keyboards.AdminResultPlayerAction.PAGE:
            await callback.answer()
            if callback.message is not None:
                await callback.message.edit_text(
                    format_admin_result_players(results, page),
                    reply_markup=keyboards.admin_result_players_keyboard(results, page),
                    parse_mode=RESULT_SUMMARY_PARSE_MODE,
                )
            return
        player = ResultService.find_result_player(results, callback_data.player_id)
        if player is None:
            await callback.answer(texts.admin.PLAYER_NOT_FOUND, show_alert=True)
            return
    except AdminAccessDeniedError:
        await callback.answer(texts.admin.ACCESS_DENIED, show_alert=True)
        return
    except (ResultTournamentNotFoundError, TournamentCheckInClosedError):
        await callback.answer(texts.admin.ADMIN_RESULTS_NOT_FOUND, show_alert=True)
        return
    except (TournamentCheckInUserNotFoundError, TournamentCheckInNotFoundError):
        await callback.answer(texts.admin.PLAYER_NOT_FOUND, show_alert=True)
        return
    except ResultValidationError as error:
        await callback.answer()
        if callback.message is not None:
            await callback.message.answer(texts.admin.admin_result_check_failed(error.errors))
        return

    await state.clear()
    await callback.answer()
    if callback.message is not None:
        editable_fields = ResultService.editable_result_fields(results)
        if editable_fields == [ResultField.PLACE]:
            await callback.message.edit_text(
                format_admin_result_field_prompt(
                    player,
                    result_field_name(keyboards.AdminResultField.PLACE),
                ),
                reply_markup=keyboards.admin_result_value_keyboard(
                    tournament_id=callback_data.tournament_id,
                    page=callback_data.page,
                    player_id=callback_data.player_id,
                    field=keyboards.AdminResultField.PLACE,
                    occupied_places=ResultService.occupied_result_places(results),
                    current_place=player.place,
                ),
            )
        else:
            await _delete_callback_message(callback)
            await callback.message.answer(
                format_admin_result_player_detail(results, player),
                reply_markup=keyboards.admin_result_player_fields_keyboard(
                    results,
                    player,
                    callback_data.page,
                ),
            )


@router.callback_query(keyboards.AdminResultFieldCallback.filter())
async def select_result_field(
    callback: CallbackQuery,
    callback_data: keyboards.AdminResultFieldCallback,
    state: FSMContext,
) -> None:
    try:
        results = await result_service.get_tournament_results(
            admin_telegram_id=callback.from_user.id,
            tournament_id=callback_data.tournament_id,
        )
        player = ResultService.find_result_player(results, callback_data.player_id)
        if player is None:
            await callback.answer(texts.admin.PLAYER_NOT_FOUND, show_alert=True)
            return

        if callback_data.action == keyboards.AdminResultFieldAction.CANCEL:
            await state.clear()
            await callback.answer(texts.admin.ADMIN_RESULTS_CANCELLED)
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer(texts.admin.ADMIN_RESULTS_CANCELLED)
            return

        await state.clear()
        await callback.answer()
        if callback.message is not None:
            await callback.message.edit_text(
                format_admin_result_field_prompt(
                    player,
                    result_field_name(callback_data.field),
                ),
                reply_markup=keyboards.admin_result_value_keyboard(
                    tournament_id=callback_data.tournament_id,
                    page=callback_data.page,
                    player_id=callback_data.player_id,
                    field=callback_data.field,
                    occupied_places=ResultService.occupied_result_places(results),
                    current_place=player.place,
                ),
            )
    except AdminAccessDeniedError:
        await callback.answer(texts.admin.ACCESS_DENIED, show_alert=True)
    except ResultTournamentNotFoundError:
        await callback.answer(texts.admin.ADMIN_RESULTS_NOT_FOUND, show_alert=True)


@router.callback_query(keyboards.AdminResultValueCallback.filter())
async def select_result_value(
    callback: CallbackQuery,
    callback_data: keyboards.AdminResultValueCallback,
    state: FSMContext,
) -> None:
    try:
        if callback_data.action == keyboards.AdminResultValueAction.CANCEL:
            await state.clear()
            await callback.answer(texts.admin.ADMIN_RESULTS_CANCELLED)
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer(texts.admin.ADMIN_RESULTS_CANCELLED)
            return

        service_field = to_result_field(callback_data.field)
        if callback_data.action == keyboards.AdminResultValueAction.SET:
            results = await result_service.update_player_result_field(
                admin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
                player_id=callback_data.player_id,
                field=service_field,
                value=callback_data.value,
            )
            player = ResultService.find_result_player(results, callback_data.player_id)
            if player is None:
                await callback.answer(texts.admin.PLAYER_NOT_FOUND, show_alert=True)
                return
            await state.clear()
            await callback.answer(texts.admin.ADMIN_RESULTS_SAVED)
            if callback.message is not None:
                page = pagination_service.paginate(
                    results.players,
                    page=callback_data.page,
                    page_size=keyboards.ADMIN_RESULT_PAGE_SIZE,
                )
                await callback.message.edit_text(
                    format_admin_result_players(results, page),
                    reply_markup=keyboards.admin_result_players_keyboard(results, page),
                    parse_mode=RESULT_SUMMARY_PARSE_MODE,
                )
            return

        results = await result_service.get_tournament_results(
            admin_telegram_id=callback.from_user.id,
            tournament_id=callback_data.tournament_id,
        )
        player = ResultService.find_result_player(results, callback_data.player_id)
        if player is None:
            await callback.answer(texts.admin.PLAYER_NOT_FOUND, show_alert=True)
            return

        if callback_data.action == keyboards.AdminResultValueAction.BACK:
            await state.clear()
            await callback.answer()
            if callback.message is not None:
                editable_fields = ResultService.editable_result_fields(results)
                if editable_fields == [ResultField.PLACE]:
                    page = pagination_service.paginate(
                        results.players,
                        page=callback_data.page,
                        page_size=keyboards.ADMIN_RESULT_PAGE_SIZE,
                    )
                    await callback.message.edit_text(
                        format_admin_result_players(results, page),
                        reply_markup=keyboards.admin_result_players_keyboard(results, page),
                        parse_mode=RESULT_SUMMARY_PARSE_MODE,
                    )
                else:
                    await callback.message.edit_text(
                        format_admin_result_player_detail(results, player),
                        reply_markup=keyboards.admin_result_player_fields_keyboard(
                            results,
                            player,
                            callback_data.page,
                        ),
                    )
            return

        if not ResultService.result_field_is_allowed(
            results.knockout_mode,
            service_field,
            results.supports_bonus_points,
        ):
            await callback.answer(texts.admin.ADMIN_RESULTS_NOT_FOUND, show_alert=True)
            return

        if callback_data.action == keyboards.AdminResultValueAction.MANUAL:
            await state.set_state(AdminResultStates.entering_manual_value)
            await state.update_data(
                result_tournament_id=callback_data.tournament_id,
                result_player_id=callback_data.player_id,
                result_page=callback_data.page,
                result_field=callback_data.field.value,
                result_prompt_message_id=callback.message.message_id
                if callback.message is not None
                else 0,
            )
            await callback.answer()
            if callback.message is not None:
                await callback.message.edit_text(
                    texts.admin.ADMIN_RESULTS_MANUAL_VALUE_PROMPTS[callback_data.field.value],
                    reply_markup=keyboards.admin_result_manual_value_keyboard(
                        tournament_id=callback_data.tournament_id,
                        page=callback_data.page,
                        player_id=callback_data.player_id,
                        field=callback_data.field,
                    ),
                )
            return
    except AdminAccessDeniedError:
        await callback.answer(texts.admin.ACCESS_DENIED, show_alert=True)
    except ResultTournamentNotFoundError:
        await callback.answer(texts.admin.ADMIN_RESULTS_NOT_FOUND, show_alert=True)
    except (ResultInvalidPlayerDataError, ResultUserNotFoundError, ValueError):
        await callback.answer(
            texts.admin.ADMIN_RESULTS_INVALID_MANUAL_VALUE[callback_data.field.value],
            show_alert=True,
        )


@router.message(AdminResultStates.entering_manual_value)
async def enter_result_manual_value(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return

    data = await state.get_data()
    tournament_id = int(data["result_tournament_id"])
    player_id = int(data["result_player_id"])
    page_number = int(data.get("result_page", 0))
    field = keyboards.AdminResultField(str(data["result_field"]))
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
        await message.answer(texts.admin.ACCESS_DENIED)
        return
    except ResultTournamentNotFoundError:
        await state.clear()
        await message.answer(texts.admin.ADMIN_RESULTS_NOT_FOUND)
        return
    except (ResultInvalidPlayerDataError, ResultUserNotFoundError, ValueError):
        await message.answer(texts.admin.ADMIN_RESULTS_INVALID_MANUAL_VALUE[field.value])
        return

    await state.clear()
    player = ResultService.find_result_player(results, player_id)
    if player is None:
        await message.answer(texts.admin.PLAYER_NOT_FOUND)
        return
    await _delete_message_by_id(
        message,
        int(data.get("result_prompt_message_id", 0)),
    )
    await message.answer(texts.admin.ADMIN_RESULTS_SAVED)
    page = pagination_service.paginate(
        results.players,
        page=page_number,
        page_size=keyboards.ADMIN_RESULT_PAGE_SIZE,
    )
    await message.answer(
        format_admin_result_players(results, page),
        reply_markup=keyboards.admin_result_players_keyboard(results, page),
        parse_mode=RESULT_SUMMARY_PARSE_MODE,
    )
