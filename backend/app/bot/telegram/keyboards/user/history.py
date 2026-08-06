from enum import StrEnum

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.telegram.keyboards import buttons
from app.services.dto import HistoricalTournamentView, HistoryMonthView, HistoryYearView
from app.services.pagination import Page

HISTORY_YEAR_PAGE_SIZE = 12
HISTORY_MONTH_PAGE_SIZE = 6
HISTORY_TOURNAMENT_PAGE_SIZE = 12
HISTORY_RESULT_PAGE_SIZE = 20


class HistoryNavAction(StrEnum):
    YEARS = "years"
    MONTHS = "months"
    TOURNAMENTS = "tournaments"
    CANCEL = "cancel"


class HistoryYearsPageCallback(CallbackData, prefix="hist_yp"):
    page: int = 0


class HistoryMonthCallback(CallbackData, prefix="hist_m"):
    year: int
    month: int
    years_page: int = 0
    months_page: int = 0


class HistoryMonthsPageCallback(CallbackData, prefix="hist_mp"):
    year: int
    page: int = 0
    years_page: int = 0


class HistoryTournamentCallback(CallbackData, prefix="hist_t"):
    tournament_id: int
    year: int
    month: int
    months_page: int = 0
    tournament_page: int = 0
    result_page: int = 0


class HistoryTournamentsPageCallback(CallbackData, prefix="hist_tp"):
    year: int
    month: int
    page: int = 0
    months_page: int = 0


class HistoryNavigationCallback(CallbackData, prefix="hist_nav"):
    action: HistoryNavAction
    year: int = 0
    month: int = 0
    page: int = 0


class HallOfFameCallback(CallbackData, prefix="hof"):
    action: str = "close"


def history_years_keyboard(page: Page[HistoryYearView]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in page.items:
        builder.button(
            text=str(item.year),
            callback_data=HistoryMonthsPageCallback(
                year=item.year,
                page=0,
                years_page=page.page,
            ),
        )
    if page.total_pages > 1:
        _add_year_navigation(builder, page)
    builder.button(
        text=buttons.CANCEL,
        callback_data=HistoryNavigationCallback(action=HistoryNavAction.CANCEL),
    )
    builder.adjust(3, 3, 3, 3, _navigation_width(page), 1)
    return builder.as_markup()


def history_months_keyboard(
    page: Page[HistoryMonthView],
    *,
    years_page: int = 0,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in page.items:
        builder.button(
            text=item.label,
            callback_data=HistoryMonthCallback(
                year=item.year,
                month=item.month,
                years_page=years_page,
                months_page=page.page,
            ),
        )
    if page.total_pages > 1:
        _add_month_navigation(builder, page, years_page=years_page)
    builder.button(
        text="↩️ К годам",
        callback_data=HistoryYearsPageCallback(page=years_page),
    )
    builder.button(
        text=buttons.CANCEL,
        callback_data=HistoryNavigationCallback(action=HistoryNavAction.CANCEL),
    )
    builder.adjust(3, 3, _navigation_width(page), 1, 1)
    return builder.as_markup()


def history_tournaments_keyboard(
    page: Page[HistoricalTournamentView],
    *,
    year: int,
    month: int,
    months_page: int = 0,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in page.items:
        builder.button(
            text=_tournament_button_text(item),
            callback_data=HistoryTournamentCallback(
                tournament_id=item.id,
                year=year,
                month=month,
                months_page=months_page,
                tournament_page=page.page,
                result_page=0,
            ),
        )
    if page.total_pages > 1:
        _add_tournament_navigation(
            builder,
            page,
            year=year,
            month=month,
            months_page=months_page,
        )
    builder.button(
        text="↩️ К месяцам",
        callback_data=HistoryMonthsPageCallback(year=year, page=months_page),
    )
    builder.button(
        text=buttons.CANCEL,
        callback_data=HistoryNavigationCallback(action=HistoryNavAction.CANCEL),
    )
    builder.adjust(3, 3, 3, 3, _navigation_width(page), 1, 1)
    return builder.as_markup()


def history_result_keyboard(
    page: Page,
    *,
    tournament_id: int,
    year: int,
    month: int,
    months_page: int,
    tournament_page: int,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if page.total_pages > 1:
        if page.has_previous:
            builder.button(
                text="⬅️",
                callback_data=HistoryTournamentCallback(
                    tournament_id=tournament_id,
                    year=year,
                    month=month,
                    months_page=months_page,
                    tournament_page=tournament_page,
                    result_page=page.previous_page,
                ),
            )
        builder.button(
            text=f"{page.page + 1}/{page.total_pages}",
            callback_data=HistoryTournamentCallback(
                tournament_id=tournament_id,
                year=year,
                month=month,
                months_page=months_page,
                tournament_page=tournament_page,
                result_page=page.page,
            ),
        )
        if page.has_next:
            builder.button(
                text="➡️",
                callback_data=HistoryTournamentCallback(
                    tournament_id=tournament_id,
                    year=year,
                    month=month,
                    months_page=months_page,
                    tournament_page=tournament_page,
                    result_page=page.next_page,
                ),
            )
    builder.button(
        text="↩️ К турнирам",
        callback_data=HistoryTournamentsPageCallback(
            year=year,
            month=month,
            page=tournament_page,
            months_page=months_page,
        ),
    )
    builder.button(
        text=buttons.CANCEL,
        callback_data=HistoryNavigationCallback(action=HistoryNavAction.CANCEL),
    )
    builder.adjust(_navigation_width(page), 1, 1)
    return builder.as_markup()


def hall_of_fame_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Закрыть", callback_data=HallOfFameCallback())
    return builder.as_markup()


def _add_year_navigation(
    builder: InlineKeyboardBuilder,
    page: Page[HistoryYearView],
) -> None:
    if page.has_previous:
        builder.button(
            text="⬅️",
            callback_data=HistoryYearsPageCallback(page=page.previous_page),
        )
    builder.button(
        text=f"{page.page + 1}/{page.total_pages}",
        callback_data=HistoryYearsPageCallback(page=page.page),
    )
    if page.has_next:
        builder.button(
            text="➡️",
            callback_data=HistoryYearsPageCallback(page=page.next_page),
        )


def _add_month_navigation(
    builder: InlineKeyboardBuilder,
    page: Page[HistoryMonthView],
    *,
    years_page: int,
) -> None:
    year = page.items[0].year if page.items else 0
    if page.has_previous:
        builder.button(
            text="⬅️",
            callback_data=HistoryMonthsPageCallback(
                year=year,
                page=page.previous_page,
                years_page=years_page,
            ),
        )
    builder.button(
        text=f"{page.page + 1}/{page.total_pages}",
        callback_data=HistoryMonthsPageCallback(
            year=year,
            page=page.page,
            years_page=years_page,
        ),
    )
    if page.has_next:
        builder.button(
            text="➡️",
            callback_data=HistoryMonthsPageCallback(
                year=year,
                page=page.next_page,
                years_page=years_page,
            ),
        )


def _add_tournament_navigation(
    builder: InlineKeyboardBuilder,
    page: Page[HistoricalTournamentView],
    *,
    year: int,
    month: int,
    months_page: int,
) -> None:
    if page.has_previous:
        builder.button(
            text="⬅️",
            callback_data=HistoryTournamentsPageCallback(
                year=year,
                month=month,
                page=page.previous_page,
                months_page=months_page,
            ),
        )
    builder.button(
        text=f"{page.page + 1}/{page.total_pages}",
        callback_data=HistoryTournamentsPageCallback(
            year=year,
            month=month,
            page=page.page,
            months_page=months_page,
        ),
    )
    if page.has_next:
        builder.button(
            text="➡️",
            callback_data=HistoryTournamentsPageCallback(
                year=year,
                month=month,
                page=page.next_page,
                months_page=months_page,
            ),
        )


def _navigation_width(page: Page) -> int:
    return 1 + int(page.has_previous) + int(page.has_next) if page.total_pages > 1 else 1


def _tournament_button_text(tournament: HistoricalTournamentView) -> str:
    label = f"{tournament.date.day:02d} {tournament.tournament_name}"
    return label if len(label) <= 32 else f"{label[:31]}…"
