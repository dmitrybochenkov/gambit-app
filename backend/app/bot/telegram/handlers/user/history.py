from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from app.bot.telegram.formatters.statistics import history as history_fmt
from app.bot.telegram.handlers.user.shared import (
    delete_message as _delete_message,
)
from app.bot.telegram.handlers.user.shared import (
    edit_history_message as _edit_history_message,
)
from app.bot.telegram.keyboards import labels
from app.bot.telegram.keyboards.user import history as user_history_kb
from app.bot.telegram.texts.user import history as text
from app.services.pagination import pagination_service
from app.services.user_statistics_service import (
    HistoricalTournamentNotFoundError,
    HistoryNotAllowedError,
    user_statistics_service,
)

router = Router(name="user.history")


@router.message(F.text == labels.MAIN_HISTORY)
async def show_history_years(message: Message) -> None:
    if message.from_user is None:
        return

    try:
        years = await user_statistics_service.list_history_years(message.from_user.id)
    except HistoryNotAllowedError:
        await message.answer(text.HISTORY_UNAVAILABLE)
        return

    page = pagination_service.paginate(
        years,
        page=0,
        page_size=user_history_kb.HISTORY_YEAR_PAGE_SIZE,
    )
    await message.answer(
        history_fmt.years(page),
        reply_markup=user_history_kb.history_years_keyboard(page),
    )


@router.callback_query(user_history_kb.HistoryYearsPageCallback.filter())
async def show_history_years_page(
    callback: CallbackQuery,
    callback_data: user_history_kb.HistoryYearsPageCallback,
) -> None:
    try:
        years = await user_statistics_service.list_history_years(callback.from_user.id)
    except HistoryNotAllowedError:
        await callback.answer(text.HISTORY_UNAVAILABLE, show_alert=True)
        return

    page = pagination_service.paginate(
        years,
        page=callback_data.page,
        page_size=user_history_kb.HISTORY_YEAR_PAGE_SIZE,
    )
    await _edit_history_message(
        callback,
        history_fmt.years(page),
        user_history_kb.history_years_keyboard(page),
    )


@router.callback_query(user_history_kb.HistoryMonthsPageCallback.filter())
async def show_history_months(
    callback: CallbackQuery,
    callback_data: user_history_kb.HistoryMonthsPageCallback,
) -> None:
    try:
        months = await user_statistics_service.list_history_months(
            telegram_id=callback.from_user.id,
            year=callback_data.year,
        )
    except HistoryNotAllowedError:
        await callback.answer(text.HISTORY_UNAVAILABLE, show_alert=True)
        return

    page = pagination_service.paginate(
        months,
        page=callback_data.page,
        page_size=user_history_kb.HISTORY_MONTH_PAGE_SIZE,
    )
    await _edit_history_message(
        callback,
        history_fmt.months(callback_data.year, page),
        user_history_kb.history_months_keyboard(page, years_page=callback_data.years_page),
    )


@router.callback_query(user_history_kb.HistoryMonthCallback.filter())
async def show_history_tournaments(
    callback: CallbackQuery,
    callback_data: user_history_kb.HistoryMonthCallback,
) -> None:
    try:
        tournaments = await user_statistics_service.list_history_tournaments(
            telegram_id=callback.from_user.id,
            year=callback_data.year,
            month=callback_data.month,
        )
    except HistoryNotAllowedError:
        await callback.answer(text.HISTORY_UNAVAILABLE, show_alert=True)
        return

    page = pagination_service.paginate(
        tournaments,
        page=0,
        page_size=user_history_kb.HISTORY_TOURNAMENT_PAGE_SIZE,
    )
    await _edit_history_message(
        callback,
        history_fmt.tournaments(callback_data.year, callback_data.month, page),
        user_history_kb.history_tournaments_keyboard(
            page,
            year=callback_data.year,
            month=callback_data.month,
            months_page=callback_data.months_page,
        ),
    )


@router.callback_query(user_history_kb.HistoryTournamentsPageCallback.filter())
async def show_history_tournaments_page(
    callback: CallbackQuery,
    callback_data: user_history_kb.HistoryTournamentsPageCallback,
) -> None:
    try:
        tournaments = await user_statistics_service.list_history_tournaments(
            telegram_id=callback.from_user.id,
            year=callback_data.year,
            month=callback_data.month,
        )
    except HistoryNotAllowedError:
        await callback.answer(text.HISTORY_UNAVAILABLE, show_alert=True)
        return

    page = pagination_service.paginate(
        tournaments,
        page=callback_data.page,
        page_size=user_history_kb.HISTORY_TOURNAMENT_PAGE_SIZE,
    )
    await _edit_history_message(
        callback,
        history_fmt.tournaments(callback_data.year, callback_data.month, page),
        user_history_kb.history_tournaments_keyboard(
            page,
            year=callback_data.year,
            month=callback_data.month,
            months_page=callback_data.months_page,
        ),
    )


@router.callback_query(user_history_kb.HistoryTournamentCallback.filter())
async def show_historical_tournament_result(
    callback: CallbackQuery,
    callback_data: user_history_kb.HistoryTournamentCallback,
) -> None:
    try:
        result = await user_statistics_service.get_historical_tournament_result(
            telegram_id=callback.from_user.id,
            tournament_id=callback_data.tournament_id,
        )
    except HistoryNotAllowedError:
        await callback.answer(text.HISTORY_UNAVAILABLE, show_alert=True)
        return
    except HistoricalTournamentNotFoundError:
        await callback.answer(text.HISTORY_TOURNAMENT_UNAVAILABLE, show_alert=True)
        return

    page = pagination_service.paginate(
        result.rows,
        page=callback_data.result_page,
        page_size=user_history_kb.HISTORY_RESULT_PAGE_SIZE,
    )
    await _edit_history_message(
        callback,
        history_fmt.tournament_result(result, page),
        user_history_kb.history_result_keyboard(
            page,
            tournament_id=callback_data.tournament_id,
            year=callback_data.year,
            month=callback_data.month,
            months_page=callback_data.months_page,
            tournament_page=callback_data.tournament_page,
        ),
        parse_mode="Markdown",
    )


@router.callback_query(user_history_kb.HistoryNavigationCallback.filter())
async def cancel_history(callback: CallbackQuery) -> None:
    await callback.answer(text.HISTORY_CLOSED)
    if callback.message is None:
        return

    await _delete_message(callback.message)
    await callback.message.answer(text.HISTORY_CLOSED)
