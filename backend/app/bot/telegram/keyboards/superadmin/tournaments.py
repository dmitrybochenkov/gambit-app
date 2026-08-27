from enum import StrEnum

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.telegram.formatters import tournaments as tournament_fmt
from app.bot.telegram.keyboards import labels
from app.bot.telegram.keyboards.admin.common import _adjust_paged_keyboard


class SuperadminTournamentHubAction(StrEnum):
    CALENDAR = "calendar"
    OPEN = "open"
    CLOSED = "closed"
    BACK = "back"


class SuperadminTournamentHubCallback(CallbackData, prefix="superadmin_tournaments"):
    action: SuperadminTournamentHubAction


class SuperadminOpenTournamentAction(StrEnum):
    PAGE = "page"
    OPEN = "open"
    DELETE_PLAYER_LIST = "delete_player_list"
    DELETE_PLAYER_PREVIEW = "delete_player_preview"
    DELETE_PLAYER_CONFIRM = "delete_player_confirm"
    CANCEL = "cancel"
    CLOSE = "close"
    BACK_TO_HUB = "back_hub"
    BACK_TO_LIST = "back_list"


class SuperadminOpenTournamentCallback(CallbackData, prefix="superadmin_open_tours"):
    action: SuperadminOpenTournamentAction
    page: int = 0
    tournament_id: int = 0
    player_id: int = 0


class SuperadminTournamentCalendarAction(StrEnum):
    MONTH = "month"
    WEEK = "week"
    DAY = "day"
    CREATE_TYPE = "create_type"
    CREATE_CONFIRM = "create_confirm"
    AUTOFILL_PREVIEW = "autofill_preview"
    AUTOFILL_CONFIRM = "autofill_confirm"
    APPROVE_PREVIEW = "approve_preview"
    APPROVE_CONFIRM = "approve_confirm"
    CHANGE_TYPE = "change_type"
    CHANGE_CONFIRM = "change_confirm"
    CHANGE_APPLY = "change_apply"
    DELETE_PREVIEW = "delete_preview"
    DELETE_CONFIRM = "delete_confirm"
    BACK_HUB = "back_hub"
    BACK_MONTH = "back_month"
    BACK_WEEK = "back_week"
    CANCEL = "cancel"


class SuperadminTournamentCalendarCallback(
    CallbackData,
    prefix="superadmin_tour_cal",
):
    action: SuperadminTournamentCalendarAction
    year: int = 0
    month: int = 0
    row: int = 0
    day: str = ""
    tournament_id: int = 0
    tournament_type_id: int = 0


def tournament_hub_keyboard(open_tournaments_count: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="📅 Календарь",
        callback_data=SuperadminTournamentHubCallback(
            action=SuperadminTournamentHubAction.CALENDAR
        ),
    )
    builder.button(
        text=f"🔑 Открытые ({open_tournaments_count})",
        callback_data=SuperadminTournamentHubCallback(action=SuperadminTournamentHubAction.OPEN),
    )
    builder.button(
        text="🔒 Закрытые",
        callback_data=SuperadminTournamentHubCallback(action=SuperadminTournamentHubAction.CLOSED),
    )
    builder.button(
        text=labels.ADMIN_CALENDAR_BACK,
        callback_data=SuperadminTournamentHubCallback(action=SuperadminTournamentHubAction.BACK),
    )
    builder.adjust(1)
    return builder.as_markup()


def calendar_month_keyboard(view: object) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for week in view.weeks:
        builder.button(
            text=str(week.row_number),
            callback_data=SuperadminTournamentCalendarCallback(
                action=SuperadminTournamentCalendarAction.WEEK,
                year=view.year,
                month=view.month,
                row=week.row_number,
            ),
        )
    previous_year, previous_month = _shift_month(view.year, view.month, -1)
    next_year, next_month = _shift_month(view.year, view.month, 1)
    builder.button(
        text="⬅️ Месяц",
        callback_data=SuperadminTournamentCalendarCallback(
            action=SuperadminTournamentCalendarAction.MONTH,
            year=previous_year,
            month=previous_month,
        ),
    )
    builder.button(
        text="Месяц ➡️",
        callback_data=SuperadminTournamentCalendarCallback(
            action=SuperadminTournamentCalendarAction.MONTH,
            year=next_year,
            month=next_month,
        ),
    )
    builder.button(
        text=labels.ADMIN_CALENDAR_BACK,
        callback_data=SuperadminTournamentCalendarCallback(
            action=SuperadminTournamentCalendarAction.BACK_HUB,
        ),
    )
    builder.adjust(len(view.weeks), 2, 1)
    return builder.as_markup()


def calendar_week_keyboard(view: object) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for day in view.days:
        builder.button(
            text=_calendar_week_day_button(day),
            callback_data=SuperadminTournamentCalendarCallback(
                action=SuperadminTournamentCalendarAction.DAY,
                year=view.year,
                month=view.month,
                row=view.row_number,
                day=day.date.isoformat(),
                tournament_id=day.tournament.id if day.tournament is not None else 0,
            ),
        )
    if view.is_empty:
        builder.button(
            text="✨ Заполнить по шаблону",
            callback_data=SuperadminTournamentCalendarCallback(
                action=SuperadminTournamentCalendarAction.AUTOFILL_PREVIEW,
                year=view.year,
                month=view.month,
                row=view.row_number,
            ),
        )
    if view.has_unapproved_tournaments:
        builder.button(
            text="✅ Утвердить неделю",
            callback_data=SuperadminTournamentCalendarCallback(
                action=SuperadminTournamentCalendarAction.APPROVE_PREVIEW,
                year=view.year,
                month=view.month,
                row=view.row_number,
            ),
        )
    if view.has_tournaments:
        from app.bot.telegram.keyboards.admin.calendar import (
            CalendarPlanAction,
            CalendarPlanCallback,
        )

        builder.button(
            text="📣 Опубликовать расписание",
            callback_data=CalendarPlanCallback(action=CalendarPlanAction.PUBLISH_PREVIEW),
        )
    builder.button(
        text=labels.ADMIN_CALENDAR_BACK,
        callback_data=SuperadminTournamentCalendarCallback(
            action=SuperadminTournamentCalendarAction.BACK_MONTH,
            year=view.year,
            month=view.month,
        ),
    )
    builder.button(
        text=labels.ADMIN_CALENDAR_CANCEL,
        callback_data=SuperadminTournamentCalendarCallback(
            action=SuperadminTournamentCalendarAction.CANCEL,
        ),
    )
    builder.adjust(*([1] * len(view.days)), 1, 1, 1, 1)
    return builder.as_markup()


def calendar_type_keyboard(
    *,
    options: list[object],
    action: SuperadminTournamentCalendarAction,
    year: int,
    month: int,
    row: int,
    day: str = "",
    tournament_id: int = 0,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for option in options:
        builder.button(
            text=option.name,
            callback_data=SuperadminTournamentCalendarCallback(
                action=action,
                year=year,
                month=month,
                row=row,
                day=day,
                tournament_id=tournament_id,
                tournament_type_id=option.id,
            ),
        )
    builder.button(
        text=labels.ADMIN_CALENDAR_BACK,
        callback_data=SuperadminTournamentCalendarCallback(
            action=SuperadminTournamentCalendarAction.BACK_WEEK,
            year=year,
            month=month,
            row=row,
        ),
    )
    builder.button(
        text=labels.ADMIN_CALENDAR_CANCEL,
        callback_data=SuperadminTournamentCalendarCallback(
            action=SuperadminTournamentCalendarAction.CANCEL,
        ),
    )
    builder.adjust(*([1] * len(options)), 1, 1)
    return builder.as_markup()


def calendar_create_preview_keyboard(
    *,
    year: int,
    month: int,
    row: int,
    day: str,
    tournament_type_id: int,
) -> InlineKeyboardMarkup:
    return _confirmation_keyboard(
        confirm=SuperadminTournamentCalendarCallback(
            action=SuperadminTournamentCalendarAction.CREATE_CONFIRM,
            year=year,
            month=month,
            row=row,
            day=day,
            tournament_type_id=tournament_type_id,
        ),
        back=SuperadminTournamentCalendarCallback(
            action=SuperadminTournamentCalendarAction.BACK_WEEK,
            year=year,
            month=month,
            row=row,
        ),
    )


def calendar_simple_confirmation_keyboard(
    *,
    confirm_action: SuperadminTournamentCalendarAction,
    year: int,
    month: int,
    row: int,
    tournament_id: int = 0,
    tournament_type_id: int = 0,
) -> InlineKeyboardMarkup:
    return _confirmation_keyboard(
        confirm=SuperadminTournamentCalendarCallback(
            action=confirm_action,
            year=year,
            month=month,
            row=row,
            tournament_id=tournament_id,
            tournament_type_id=tournament_type_id,
        ),
        back=SuperadminTournamentCalendarCallback(
            action=SuperadminTournamentCalendarAction.BACK_WEEK,
            year=year,
            month=month,
            row=row,
        ),
    )


def calendar_occupied_tournament_keyboard(
    day: object,
    *,
    year: int,
    month: int,
    row: int,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if day.editable_future and day.tournament is not None:
        builder.button(
            text="✏️ Изменить тип",
            callback_data=SuperadminTournamentCalendarCallback(
                action=SuperadminTournamentCalendarAction.CHANGE_TYPE,
                year=year,
                month=month,
                row=row,
                tournament_id=day.tournament.id,
            ),
        )
        builder.button(
            text="🗑 Удалить турнир",
            callback_data=SuperadminTournamentCalendarCallback(
                action=SuperadminTournamentCalendarAction.DELETE_PREVIEW,
                year=year,
                month=month,
                row=row,
                tournament_id=day.tournament.id,
            ),
        )
    builder.button(
        text=labels.ADMIN_CALENDAR_BACK,
        callback_data=SuperadminTournamentCalendarCallback(
            action=SuperadminTournamentCalendarAction.BACK_WEEK,
            year=year,
            month=month,
            row=row,
        ),
    )
    builder.button(
        text=labels.ADMIN_CALENDAR_CANCEL,
        callback_data=SuperadminTournamentCalendarCallback(
            action=SuperadminTournamentCalendarAction.CANCEL,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def _confirmation_keyboard(
    *,
    confirm: SuperadminTournamentCalendarCallback,
    back: SuperadminTournamentCalendarCallback,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data=confirm)
    builder.button(text=labels.ADMIN_CALENDAR_BACK, callback_data=back)
    builder.button(
        text=labels.ADMIN_CALENDAR_CANCEL,
        callback_data=SuperadminTournamentCalendarCallback(
            action=SuperadminTournamentCalendarAction.CANCEL
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def _calendar_week_day_button(day: object) -> str:
    weekday = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][day.date.weekday()]
    base = f"{day.date.day:02d} {weekday}"
    if day.tournament is None:
        return base
    return f"{base} — {day.tournament.tournament_type_name} ({day.registrations_count})"


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    month += delta
    if month < 1:
        return year - 1, 12
    if month > 12:
        return year + 1, 1
    return year, month


def open_tournament_list_keyboard(page: object) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in page.items:
        builder.button(
            text=tournament_fmt.short_label(item.tournament),
            callback_data=SuperadminOpenTournamentCallback(
                action=SuperadminOpenTournamentAction.OPEN,
                page=page.page,
                tournament_id=item.tournament.id,
            ),
        )
    if page.total_pages > 1:
        if page.has_previous:
            builder.button(
                text="⬅️",
                callback_data=SuperadminOpenTournamentCallback(
                    action=SuperadminOpenTournamentAction.PAGE,
                    page=page.previous_page,
                ),
            )
        builder.button(
            text=f"{page.page + 1}/{page.total_pages}",
            callback_data=SuperadminOpenTournamentCallback(
                action=SuperadminOpenTournamentAction.PAGE,
                page=page.page,
            ),
        )
        if page.has_next:
            builder.button(
                text="➡️",
                callback_data=SuperadminOpenTournamentCallback(
                    action=SuperadminOpenTournamentAction.PAGE,
                    page=page.next_page,
                ),
            )
    builder.button(
        text=labels.ADMIN_CALENDAR_BACK,
        callback_data=SuperadminOpenTournamentCallback(
            action=SuperadminOpenTournamentAction.BACK_TO_HUB,
            page=page.page,
        ),
    )
    _adjust_paged_keyboard(builder, page, item_rows=[1] * len(page.items))
    return builder.as_markup()


def open_tournament_card_keyboard(
    *,
    tournament_id: int,
    page: int,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🗑 Удалить игрока",
        callback_data=SuperadminOpenTournamentCallback(
            action=SuperadminOpenTournamentAction.DELETE_PLAYER_LIST,
            tournament_id=tournament_id,
            page=page,
        ),
    )
    builder.button(
        text=labels.ADMIN_PANEL_CLOSE_TOURNAMENT,
        callback_data=SuperadminOpenTournamentCallback(
            action=SuperadminOpenTournamentAction.CLOSE,
            tournament_id=tournament_id,
            page=page,
        ),
    )
    builder.button(
        text=labels.ADMIN_CALENDAR_BACK,
        callback_data=SuperadminOpenTournamentCallback(
            action=SuperadminOpenTournamentAction.BACK_TO_LIST,
            tournament_id=tournament_id,
            page=page,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def open_tournament_player_delete_list_keyboard(
    *,
    tournament_id: int,
    page: object,
    tournament_page: int,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for player in page.items:
        builder.button(
            text=player.display_name,
            callback_data=SuperadminOpenTournamentCallback(
                action=SuperadminOpenTournamentAction.DELETE_PLAYER_PREVIEW,
                tournament_id=tournament_id,
                player_id=player.player_id,
                page=tournament_page,
            ),
        )
    builder.button(
        text=labels.ADMIN_CALENDAR_BACK,
        callback_data=SuperadminOpenTournamentCallback(
            action=SuperadminOpenTournamentAction.OPEN,
            tournament_id=tournament_id,
            page=tournament_page,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def open_tournament_player_delete_confirmation_keyboard(
    *,
    tournament_id: int,
    player_id: int,
    page: int,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🗑 Да, удалить",
        callback_data=SuperadminOpenTournamentCallback(
            action=SuperadminOpenTournamentAction.DELETE_PLAYER_CONFIRM,
            tournament_id=tournament_id,
            player_id=player_id,
            page=page,
        ),
    )
    builder.button(
        text=labels.ADMIN_CALENDAR_BACK,
        callback_data=SuperadminOpenTournamentCallback(
            action=SuperadminOpenTournamentAction.DELETE_PLAYER_LIST,
            tournament_id=tournament_id,
            page=page,
        ),
    )
    builder.button(
        text=labels.ADMIN_CALENDAR_CANCEL,
        callback_data=SuperadminOpenTournamentCallback(
            action=SuperadminOpenTournamentAction.CANCEL,
            tournament_id=tournament_id,
            page=page,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()
