# ruff: noqa: F403,F405
from aiogram import Router

from app.bot.telegram.handlers.user.common import *  # noqa: F403

router = Router(name="user.history")


@router.message(F.text == keyboards.MAIN_HISTORY)
async def show_history_years(message: Message) -> None:
    if message.from_user is None:
        return

    try:
        years = await user_statistics_service.list_history_years(message.from_user.id)
    except HistoryNotAllowedError:
        await message.answer(texts.user.HISTORY_UNAVAILABLE)
        return

    page = pagination_service.paginate(
        years,
        page=0,
        page_size=keyboards.HISTORY_YEAR_PAGE_SIZE,
    )
    await message.answer(
        format_history_years(page),
        reply_markup=keyboards.history_years_keyboard(page),
    )


@router.callback_query(keyboards.HistoryYearsPageCallback.filter())
async def show_history_years_page(
    callback: CallbackQuery,
    callback_data: keyboards.HistoryYearsPageCallback,
) -> None:
    try:
        years = await user_statistics_service.list_history_years(callback.from_user.id)
    except HistoryNotAllowedError:
        await callback.answer(texts.user.HISTORY_UNAVAILABLE, show_alert=True)
        return

    page = pagination_service.paginate(
        years,
        page=callback_data.page,
        page_size=keyboards.HISTORY_YEAR_PAGE_SIZE,
    )
    await _edit_history_message(
        callback,
        format_history_years(page),
        keyboards.history_years_keyboard(page),
    )


@router.callback_query(keyboards.HistoryMonthsPageCallback.filter())
async def show_history_months(
    callback: CallbackQuery,
    callback_data: keyboards.HistoryMonthsPageCallback,
) -> None:
    try:
        months = await user_statistics_service.list_history_months(
            telegram_id=callback.from_user.id,
            year=callback_data.year,
        )
    except HistoryNotAllowedError:
        await callback.answer(texts.user.HISTORY_UNAVAILABLE, show_alert=True)
        return

    page = pagination_service.paginate(
        months,
        page=callback_data.page,
        page_size=keyboards.HISTORY_MONTH_PAGE_SIZE,
    )
    await _edit_history_message(
        callback,
        format_history_months(callback_data.year, page),
        keyboards.history_months_keyboard(page, years_page=callback_data.years_page),
    )


@router.callback_query(keyboards.HistoryMonthCallback.filter())
async def show_history_tournaments(
    callback: CallbackQuery,
    callback_data: keyboards.HistoryMonthCallback,
) -> None:
    try:
        tournaments = await user_statistics_service.list_history_tournaments(
            telegram_id=callback.from_user.id,
            year=callback_data.year,
            month=callback_data.month,
        )
    except HistoryNotAllowedError:
        await callback.answer(texts.user.HISTORY_UNAVAILABLE, show_alert=True)
        return

    page = pagination_service.paginate(
        tournaments,
        page=0,
        page_size=keyboards.HISTORY_TOURNAMENT_PAGE_SIZE,
    )
    await _edit_history_message(
        callback,
        format_history_tournaments(callback_data.year, callback_data.month, page),
        keyboards.history_tournaments_keyboard(
            page,
            year=callback_data.year,
            month=callback_data.month,
            months_page=callback_data.months_page,
        ),
    )


@router.callback_query(keyboards.HistoryTournamentsPageCallback.filter())
async def show_history_tournaments_page(
    callback: CallbackQuery,
    callback_data: keyboards.HistoryTournamentsPageCallback,
) -> None:
    try:
        tournaments = await user_statistics_service.list_history_tournaments(
            telegram_id=callback.from_user.id,
            year=callback_data.year,
            month=callback_data.month,
        )
    except HistoryNotAllowedError:
        await callback.answer(texts.user.HISTORY_UNAVAILABLE, show_alert=True)
        return

    page = pagination_service.paginate(
        tournaments,
        page=callback_data.page,
        page_size=keyboards.HISTORY_TOURNAMENT_PAGE_SIZE,
    )
    await _edit_history_message(
        callback,
        format_history_tournaments(callback_data.year, callback_data.month, page),
        keyboards.history_tournaments_keyboard(
            page,
            year=callback_data.year,
            month=callback_data.month,
            months_page=callback_data.months_page,
        ),
    )


@router.callback_query(keyboards.HistoryTournamentCallback.filter())
async def show_historical_tournament_result(
    callback: CallbackQuery,
    callback_data: keyboards.HistoryTournamentCallback,
) -> None:
    try:
        result = await user_statistics_service.get_historical_tournament_result(
            telegram_id=callback.from_user.id,
            tournament_id=callback_data.tournament_id,
        )
    except HistoryNotAllowedError:
        await callback.answer(texts.user.HISTORY_UNAVAILABLE, show_alert=True)
        return
    except HistoricalTournamentNotFoundError:
        await callback.answer(texts.user.HISTORY_TOURNAMENT_UNAVAILABLE, show_alert=True)
        return

    page = pagination_service.paginate(
        result.rows,
        page=callback_data.result_page,
        page_size=keyboards.HISTORY_RESULT_PAGE_SIZE,
    )
    await _edit_history_message(
        callback,
        format_historical_tournament_result(result, page),
        keyboards.history_result_keyboard(
            page,
            tournament_id=callback_data.tournament_id,
            year=callback_data.year,
            month=callback_data.month,
            months_page=callback_data.months_page,
            tournament_page=callback_data.tournament_page,
        ),
        parse_mode="Markdown",
    )


@router.callback_query(keyboards.HistoryNavigationCallback.filter())
async def cancel_history(callback: CallbackQuery) -> None:
    await callback.answer(texts.user.HISTORY_CLOSED)
    if callback.message is None:
        return

    await _delete_message(callback.message)
    await callback.message.answer(texts.user.HISTORY_CLOSED)
