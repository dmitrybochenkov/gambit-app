import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.telegram.formatters import results as result_fmt
from app.bot.telegram.handlers.admin.shared import (
    RESULT_SUMMARY_PARSE_MODE,
)
from app.bot.telegram.handlers.admin.shared import (
    delete_callback_message as _delete_callback_message,
)
from app.bot.telegram.keyboards import labels
from app.bot.telegram.keyboards.admin import results as admin_results_kb
from app.bot.telegram.keyboards.superadmin import panel as superadmin_panel_kb
from app.bot.telegram.keyboards.superadmin import tournament_close as superadmin_tournament_close_kb
from app.bot.telegram.states import AdminResultStates
from app.bot.telegram.texts.superadmin import panel as panel_text
from app.bot.telegram.texts.superadmin import tournament_close as text
from app.services.access_policy import AdminAccessDeniedError
from app.services.pagination import pagination_service
from app.services.result_service import (
    FutureTournamentCannotBeClosedError,
    ResultInvalidFundError,
    ResultService,
    ResultTournamentNotFoundError,
    ResultValidationError,
    result_service,
)

logger = logging.getLogger(__name__)


router = Router(name="admin.tournament_close")


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

    if not tournaments:
        await message.answer(
            "Нет незакрытых турниров.",
            reply_markup=superadmin_panel_kb.superadmin_panel_keyboard(),
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
        page_size=admin_results_kb.ADMIN_RESULT_PAGE_SIZE,
    )
    await message.answer(
        result_fmt.close_tournament_list(page),
        reply_markup=superadmin_tournament_close_kb.admin_close_tournament_list_keyboard(page),
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
                await callback.message.answer(
                    text.ADMIN_RESULTS_CANCELLED,
                    reply_markup=superadmin_panel_kb.superadmin_panel_keyboard(),
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
                await callback.message.edit_text(
                    result_fmt.close_tournament_list(page),
                    reply_markup=superadmin_tournament_close_kb.admin_close_tournament_list_keyboard(
                        page
                    ),
                )
            return

        if callback_data.action == superadmin_tournament_close_kb.AdminCloseTournamentAction.BACK:
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
                    page_size=admin_results_kb.ADMIN_RESULT_PAGE_SIZE,
                )
                await callback.message.edit_text(
                    result_fmt.close_tournament_list(page),
                    reply_markup=superadmin_tournament_close_kb.admin_close_tournament_list_keyboard(
                        page
                    ),
                )
                return
            await _delete_callback_message(callback)
            await callback.message.answer(
                "Добро пожаловать в админ-панель.",
                reply_markup=superadmin_panel_kb.superadmin_panel_keyboard(),
            )
            return

        if callback_data.action in {
            superadmin_tournament_close_kb.AdminCloseTournamentAction.OPEN,
            superadmin_tournament_close_kb.AdminCloseTournamentAction.ENTER_FUND,
            superadmin_tournament_close_kb.AdminCloseTournamentAction.CHANGE_FUND,
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
            await callback.answer("Турнир закрыт.")
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer(
                    result_fmt.closed_tournament(results),
                    parse_mode=RESULT_SUMMARY_PARSE_MODE,
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

    await callback.answer(text.ADMIN_RESULTS_NOT_FOUND, show_alert=True)


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
    errors = await result_service.validate_closeable_results(
        superadmin_telegram_id=superadmin_telegram_id,
        tournament_id=tournament_id,
    )
    if errors:
        await state.clear()
        await message.answer(
            result_fmt.close_tournament_blocked(errors),
            reply_markup=superadmin_tournament_close_kb.admin_close_tournament_card_keyboard(
                tournament_id=tournament_id,
                page=page,
            ),
        )
        return
    await state.set_state(AdminResultStates.entering_tournament_fund)
    await state.update_data(close_tournament_id=tournament_id, close_tournament_page=page)
    await message.answer(
        result_fmt.close_tournament_card(results),
        reply_markup=superadmin_tournament_close_kb.admin_close_tournament_card_keyboard(
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
    results = await result_service.get_closeable_tournament_results(
        superadmin_telegram_id=callback.from_user.id,
        tournament_id=tournament_id,
    )
    errors = await result_service.validate_closeable_results(
        superadmin_telegram_id=callback.from_user.id,
        tournament_id=tournament_id,
    )
    if errors:
        await state.clear()
        await callback.message.edit_text(
            result_fmt.close_tournament_blocked(errors),
            reply_markup=superadmin_tournament_close_kb.admin_close_tournament_card_keyboard(
                tournament_id=tournament_id,
                page=page,
            ),
        )
        return
    await state.set_state(AdminResultStates.entering_tournament_fund)
    await state.update_data(close_tournament_id=tournament_id, close_tournament_page=page)
    await callback.message.edit_text(
        result_fmt.close_tournament_card(results),
        reply_markup=superadmin_tournament_close_kb.admin_close_tournament_card_keyboard(
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
        results = await result_service.get_closeable_tournament_results(
            superadmin_telegram_id=message.from_user.id,
            tournament_id=tournament_id,
        )
    except (ValueError, ResultInvalidFundError):
        await message.answer(
            result_fmt.tournament_fund_error(),
            reply_markup=superadmin_tournament_close_kb.admin_close_tournament_fund_error_keyboard(
                tournament_id=tournament_id,
                page=page_number,
            ),
        )
        return
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

    await state.update_data(tournament_fund=int(tournament_fund))
    await state.set_state(None)
    await message.answer(
        result_fmt.close_tournament_confirmation(results, tournament_fund),
        reply_markup=superadmin_tournament_close_kb.admin_close_tournament_confirmation_keyboard(
            tournament_id=tournament_id,
            page=page_number,
        ),
        parse_mode=RESULT_SUMMARY_PARSE_MODE,
    )
