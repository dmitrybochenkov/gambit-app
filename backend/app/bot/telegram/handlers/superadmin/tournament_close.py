# ruff: noqa: F403,F405
from aiogram import Router

from app.bot.telegram.handlers.admin.common import *  # noqa: F403

router = Router(name="admin.tournament_close")


@router.message(F.text == keyboards.ADMIN_PANEL_CLOSE_TOURNAMENT)
async def show_close_tournament_flow(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return
    await state.clear()
    try:
        tournaments = await result_service.list_unclosed_tournaments_for_superadmin(
            message.from_user.id
        )
    except AdminAccessDeniedError:
        await message.answer(texts.admin.INSUFFICIENT_RIGHTS)
        return

    if not tournaments:
        await message.answer(
            "Нет незакрытых турниров.",
            reply_markup=keyboards.superadmin_panel_keyboard(),
        )
        return

    if len(tournaments) == 1:
        await _send_close_tournament_card(
            message=message,
            state=state,
            superadmin_telegram_id=message.from_user.id,
            tournament_id=tournaments[0].id,
            page=0,
        )
        return

    page = pagination_service.paginate(
        tournaments,
        page=0,
        page_size=keyboards.ADMIN_RESULT_PAGE_SIZE,
    )
    await message.answer(
        format_admin_close_tournament_list(page),
        reply_markup=keyboards.admin_close_tournament_list_keyboard(page),
    )


@router.callback_query(keyboards.AdminCloseTournamentCallback.filter())
async def select_close_tournament_action(
    callback: CallbackQuery,
    callback_data: keyboards.AdminCloseTournamentCallback,
    state: FSMContext,
) -> None:
    try:
        if callback_data.action == keyboards.AdminCloseTournamentAction.CANCEL:
            await state.clear()
            await callback.answer(texts.admin.ADMIN_RESULTS_CANCELLED)
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer(
                    texts.admin.ADMIN_RESULTS_CANCELLED,
                    reply_markup=keyboards.superadmin_panel_keyboard(),
                )
            return

        if callback_data.action == keyboards.AdminCloseTournamentAction.PAGE:
            tournaments = await result_service.list_unclosed_tournaments_for_superadmin(
                callback.from_user.id
            )
            page = pagination_service.paginate(
                tournaments,
                page=callback_data.page,
                page_size=keyboards.ADMIN_RESULT_PAGE_SIZE,
            )
            await callback.answer()
            if callback.message is not None:
                await callback.message.edit_text(
                    format_admin_close_tournament_list(page),
                    reply_markup=keyboards.admin_close_tournament_list_keyboard(page),
                )
            return

        if callback_data.action == keyboards.AdminCloseTournamentAction.BACK:
            await state.clear()
            tournaments = await result_service.list_unclosed_tournaments_for_superadmin(
                callback.from_user.id
            )
            await callback.answer()
            if callback.message is None:
                return
            if len(tournaments) > 1:
                page = pagination_service.paginate(
                    tournaments,
                    page=callback_data.page,
                    page_size=keyboards.ADMIN_RESULT_PAGE_SIZE,
                )
                await callback.message.edit_text(
                    format_admin_close_tournament_list(page),
                    reply_markup=keyboards.admin_close_tournament_list_keyboard(page),
                )
                return
            await _delete_callback_message(callback)
            await callback.message.answer(
                "Добро пожаловать в админ-панель.",
                reply_markup=keyboards.superadmin_panel_keyboard(),
            )
            return

        if callback_data.action in {
            keyboards.AdminCloseTournamentAction.OPEN,
            keyboards.AdminCloseTournamentAction.ENTER_FUND,
            keyboards.AdminCloseTournamentAction.CHANGE_FUND,
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

        if callback_data.action == keyboards.AdminCloseTournamentAction.CONFIRM:
            data = await state.get_data()
            tournament_fund = int(data["tournament_fund"])
            results = await result_service.close_tournament(
                superadmin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
                tournament_fund=tournament_fund,
            )
            await state.clear()
            await callback.answer("Турнир закрыт.")
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer(
                    format_admin_closed_tournament(results),
                    parse_mode=RESULT_SUMMARY_PARSE_MODE,
                )
            return
    except AdminAccessDeniedError:
        await callback.answer(texts.admin.ACCESS_DENIED, show_alert=True)
        return
    except ResultInvalidFundError:
        await callback.answer(format_admin_tournament_fund_error(), show_alert=True)
        return
    except ResultTournamentNotFoundError:
        await callback.answer(texts.admin.ADMIN_RESULTS_NOT_FOUND, show_alert=True)
        return
    except ResultValidationError as error:
        await callback.answer()
        if callback.message is not None:
            await callback.message.answer(format_admin_close_tournament_blocked(error.errors))
        return

    await callback.answer(texts.admin.ADMIN_RESULTS_NOT_FOUND, show_alert=True)


async def _send_close_tournament_card(
    *,
    message: Message,
    state: FSMContext,
    superadmin_telegram_id: int,
    tournament_id: int,
    page: int,
) -> None:
    results = await result_service.get_tournament_results(
        admin_telegram_id=superadmin_telegram_id,
        tournament_id=tournament_id,
    )
    errors = await result_service.validate_results(
        admin_telegram_id=superadmin_telegram_id,
        tournament_id=tournament_id,
    )
    if errors:
        await state.clear()
        await message.answer(
            format_admin_close_tournament_blocked(errors),
            reply_markup=keyboards.admin_close_tournament_card_keyboard(
                tournament_id=tournament_id,
                page=page,
            ),
        )
        return
    await state.set_state(AdminResultStates.entering_tournament_fund)
    await state.update_data(close_tournament_id=tournament_id, close_tournament_page=page)
    await message.answer(
        format_admin_close_tournament_card(results),
        reply_markup=keyboards.admin_close_tournament_card_keyboard(
            tournament_id=tournament_id,
            page=page,
        ),
        parse_mode=RESULT_SUMMARY_PARSE_MODE,
    )


async def _edit_close_tournament_card(
    *,
    callback: CallbackQuery,
    state: FSMContext,
    tournament_id: int,
    page: int,
) -> None:
    results = await result_service.get_tournament_results(
        admin_telegram_id=callback.from_user.id,
        tournament_id=tournament_id,
    )
    errors = await result_service.validate_results(
        admin_telegram_id=callback.from_user.id,
        tournament_id=tournament_id,
    )
    if errors:
        await state.clear()
        await callback.message.edit_text(
            format_admin_close_tournament_blocked(errors),
            reply_markup=keyboards.admin_close_tournament_card_keyboard(
                tournament_id=tournament_id,
                page=page,
            ),
        )
        return
    await state.set_state(AdminResultStates.entering_tournament_fund)
    await state.update_data(close_tournament_id=tournament_id, close_tournament_page=page)
    await callback.message.edit_text(
        format_admin_close_tournament_card(results),
        reply_markup=keyboards.admin_close_tournament_card_keyboard(
            tournament_id=tournament_id,
            page=page,
        ),
        parse_mode=RESULT_SUMMARY_PARSE_MODE,
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
        results = await result_service.get_tournament_results(
            admin_telegram_id=message.from_user.id,
            tournament_id=tournament_id,
        )
    except (ValueError, ResultInvalidFundError):
        await message.answer(
            format_admin_tournament_fund_error(),
            reply_markup=keyboards.admin_close_tournament_fund_error_keyboard(
                tournament_id=tournament_id,
                page=page_number,
            ),
        )
        return
    except AdminAccessDeniedError:
        await state.clear()
        await message.answer(texts.admin.ACCESS_DENIED)
        return
    except ResultTournamentNotFoundError:
        await state.clear()
        await message.answer(texts.admin.ADMIN_RESULTS_NOT_FOUND)
        return

    await state.update_data(tournament_fund=int(tournament_fund))
    await state.set_state(None)
    await message.answer(
        format_admin_close_tournament_confirmation(results, tournament_fund),
        reply_markup=keyboards.admin_close_tournament_confirmation_keyboard(
            tournament_id=tournament_id,
            page=page_number,
        ),
        parse_mode=RESULT_SUMMARY_PARSE_MODE,
    )
