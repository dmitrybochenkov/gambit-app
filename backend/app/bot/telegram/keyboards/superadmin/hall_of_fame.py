from enum import StrEnum

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.telegram.formatters.statistics.achievements import achievement_shows_date
from app.bot.telegram.keyboards import labels
from app.bot.telegram.keyboards.admin.common import _adjust_paged_keyboard
from app.services.dto.hall_of_fame import HallOfFameCandidateView, HallOfFameSeasonListItemView
from app.services.pagination import Page

PAGE_SIZE = 5


class HallOfFameField(StrEnum):
    RATING_WINNER = "rating_winner"
    KO_RATING_WINNER = "ko_rating_winner"
    GRAND_SEASON = "grand_season"
    GRAND_MONTH = "grand_month"
    GRAND_KNOCKOUT = "grand_knockout"


class HallOfFameSeasonAction(StrEnum):
    OPEN = "open"
    PAGE = "page"
    CANCEL = "cancel"


class HallOfFameSeasonCallback(CallbackData, prefix="hof_season"):
    action: HallOfFameSeasonAction
    page: int = 0
    season_id: int = 0


class HallOfFameCardAction(StrEnum):
    PHOTOS = "photos"
    ACHIEVEMENTS = "achievements"
    SELECT_KIND = "select_kind"
    DELETE_ACHIEVEMENT = "delete_achievement"
    BACK = "back"
    BACK_HUB = "back_hub"
    CANCEL = "cancel"


class HallOfFameCardCallback(CallbackData, prefix="hof_card"):
    action: HallOfFameCardAction
    season_id: int
    page: int = 0
    kind: HallOfFameField = HallOfFameField.RATING_WINNER


class HallOfFameDateAction(StrEnum):
    TODAY = "today"
    BACK = "back"
    CANCEL = "cancel"


class HallOfFameDateCallback(CallbackData, prefix="hof_date"):
    action: HallOfFameDateAction
    season_id: int
    field: HallOfFameField


class HallOfFameSearchAction(StrEnum):
    OPEN = "open"
    BACK_DATE = "back_date"
    BACK_NAME = "back_name"
    CANCEL = "cancel"


class HallOfFameSearchCallback(CallbackData, prefix="hof_search"):
    action: HallOfFameSearchAction
    season_id: int
    field: HallOfFameField
    player_id: int = 0


class HallOfFameConfirmAction(StrEnum):
    CONFIRM = "confirm"
    BACK = "back"
    CANCEL = "cancel"


class HallOfFameConfirmCallback(CallbackData, prefix="hof_confirm"):
    action: HallOfFameConfirmAction
    season_id: int
    field: HallOfFameField
    player_id: int


class HallOfFamePhotoAction(StrEnum):
    OPEN_ADD = "open_add"
    DELETE_ALL = "delete_all"
    CONFIRM_DELETE_ALL = "confirm_delete_all"
    SAVE = "save"
    BACK_CARD = "back_card"
    BACK_MENU = "back_menu"
    CANCEL = "cancel"


class HallOfFamePhotoCallback(CallbackData, prefix="hof_photo"):
    action: HallOfFamePhotoAction
    season_id: int


class HallOfFameDeleteAction(StrEnum):
    OPEN = "open"
    CONFIRM = "confirm"
    BACK_MENU = "back_menu"
    BACK_LIST = "back_list"
    CANCEL = "cancel"


class HallOfFameDeleteCallback(CallbackData, prefix="hof_delete"):
    action: HallOfFameDeleteAction
    season_id: int
    achievement_id: int = 0


def seasons_keyboard(page: Page[HallOfFameSeasonListItemView]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for season in page.items:
        builder.button(
            text=season.season_name,
            callback_data=HallOfFameSeasonCallback(
                action=HallOfFameSeasonAction.OPEN,
                page=page.page,
                season_id=season.season_id,
            ),
        )
    if page.total_pages > 1:
        if page.has_previous:
            builder.button(
                text="⬅️",
                callback_data=HallOfFameSeasonCallback(
                    action=HallOfFameSeasonAction.PAGE,
                    page=page.previous_page,
                ),
            )
        builder.button(
            text=f"{page.page + 1}/{page.total_pages}",
            callback_data=HallOfFameSeasonCallback(
                action=HallOfFameSeasonAction.PAGE,
                page=page.page,
            ),
        )
        if page.has_next:
            builder.button(
                text="➡️",
                callback_data=HallOfFameSeasonCallback(
                    action=HallOfFameSeasonAction.PAGE,
                    page=page.next_page,
                ),
            )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=HallOfFameSeasonCallback(
            action=HallOfFameSeasonAction.CANCEL,
            page=page.page,
        ),
    )
    _adjust_paged_keyboard(builder, page, item_rows=[1] * len(page.items), footer_rows=[1])
    return builder.as_markup()


def season_card_keyboard(*, entry: object, page: int) -> InlineKeyboardMarkup:
    season_id = entry.season_id
    builder = InlineKeyboardBuilder()
    builder.button(
        text="📸 Фото",
        callback_data=HallOfFameCardCallback(
            action=HallOfFameCardAction.PHOTOS, season_id=season_id, page=page
        ),
    )
    builder.button(
        text="🏆 Награды",
        callback_data=HallOfFameCardCallback(
            action=HallOfFameCardAction.ACHIEVEMENTS, season_id=season_id, page=page
        ),
    )
    builder.button(
        text="⬅️ Назад",
        callback_data=HallOfFameCardCallback(
            action=HallOfFameCardAction.BACK,
            season_id=season_id,
            page=page,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=HallOfFameCardCallback(
            action=HallOfFameCardAction.CANCEL,
            season_id=season_id,
            page=page,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def achievements_keyboard(*, entry: object, page: int) -> InlineKeyboardMarkup:
    season_id = entry.season_id
    builder = InlineKeyboardBuilder()
    for achievement_type in entry.achievement_types:
        kind = HallOfFameField(achievement_type.kind)
        builder.button(
            text=f"{achievement_type.emoji} {achievement_type.title}",
            callback_data=HallOfFameCardCallback(
                action=HallOfFameCardAction.SELECT_KIND,
                season_id=season_id,
                page=page,
                kind=kind,
            ),
        )
    if entry.achievements:
        builder.button(
            text="🗑 Удалить награду",
            callback_data=HallOfFameCardCallback(
                action=HallOfFameCardAction.DELETE_ACHIEVEMENT,
                season_id=season_id,
                page=page,
            ),
        )
    builder.button(
        text="⬅️ Назад",
        callback_data=HallOfFameCardCallback(
            action=HallOfFameCardAction.BACK_HUB,
            season_id=season_id,
            page=page,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=HallOfFameCardCallback(
            action=HallOfFameCardAction.CANCEL,
            season_id=season_id,
            page=page,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def date_prompt_keyboard(
    *, season_id: int, field: HallOfFameField, today_label: str
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"📅 Сегодня — {today_label}",
        callback_data=HallOfFameDateCallback(
            action=HallOfFameDateAction.TODAY, season_id=season_id, field=field
        ),
    )
    builder.button(
        text="⬅️ Назад",
        callback_data=HallOfFameDateCallback(
            action=HallOfFameDateAction.BACK, season_id=season_id, field=field
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=HallOfFameDateCallback(
            action=HallOfFameDateAction.CANCEL, season_id=season_id, field=field
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def photo_menu_keyboard(*, season_id: int, page: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="➕ Добавить фото",
        callback_data=HallOfFamePhotoCallback(
            action=HallOfFamePhotoAction.OPEN_ADD, season_id=season_id
        ),
    )
    builder.button(
        text="🗑 Удалить все фото",
        callback_data=HallOfFamePhotoCallback(
            action=HallOfFamePhotoAction.DELETE_ALL, season_id=season_id
        ),
    )
    builder.button(
        text="⬅️ Назад",
        callback_data=HallOfFamePhotoCallback(
            action=HallOfFamePhotoAction.BACK_CARD, season_id=season_id
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=HallOfFamePhotoCallback(
            action=HallOfFamePhotoAction.CANCEL, season_id=season_id
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def photo_delete_confirmation_keyboard(*, season_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Удалить все",
        callback_data=HallOfFamePhotoCallback(
            action=HallOfFamePhotoAction.CONFIRM_DELETE_ALL, season_id=season_id
        ),
    )
    builder.button(
        text="⬅️ Назад",
        callback_data=HallOfFamePhotoCallback(
            action=HallOfFamePhotoAction.BACK_MENU, season_id=season_id
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=HallOfFamePhotoCallback(
            action=HallOfFamePhotoAction.CANCEL, season_id=season_id
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def search_prompt_keyboard(*, season_id: int, field: HallOfFameField) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="⬅️ Назад",
        callback_data=HallOfFameSearchCallback(
            action=HallOfFameSearchAction.BACK_DATE,
            season_id=season_id,
            field=field,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=HallOfFameSearchCallback(
            action=HallOfFameSearchAction.CANCEL,
            season_id=season_id,
            field=field,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def search_results_keyboard(
    *,
    season_id: int,
    field: HallOfFameField,
    candidates: list[HallOfFameCandidateView],
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for candidate in candidates:
        builder.button(
            text=candidate.user.display_name,
            callback_data=HallOfFameSearchCallback(
                action=HallOfFameSearchAction.OPEN,
                season_id=season_id,
                field=field,
                player_id=candidate.user.id,
            ),
        )
    builder.button(
        text="⬅️ Назад",
        callback_data=HallOfFameSearchCallback(
            action=HallOfFameSearchAction.BACK_NAME,
            season_id=season_id,
            field=field,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=HallOfFameSearchCallback(
            action=HallOfFameSearchAction.CANCEL,
            season_id=season_id,
            field=field,
        ),
    )
    builder.adjust(*([1] * len(candidates)), 1, 1)
    return builder.as_markup()


def delete_achievements_keyboard(*, entry: object) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for achievement in entry.achievements:
        suffix = (
            f" — {achievement.awarded_at:%d.%m}" if achievement_shows_date(achievement.kind) else ""
        )
        builder.button(
            text=(f"{achievement.emoji} {achievement.player.display_name}{suffix}"),
            callback_data=HallOfFameDeleteCallback(
                action=HallOfFameDeleteAction.OPEN,
                season_id=entry.season_id,
                achievement_id=achievement.id,
            ),
        )
    builder.button(
        text="⬅️ Назад",
        callback_data=HallOfFameDeleteCallback(
            action=HallOfFameDeleteAction.BACK_MENU,
            season_id=entry.season_id,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=HallOfFameDeleteCallback(
            action=HallOfFameDeleteAction.CANCEL,
            season_id=entry.season_id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def delete_achievement_confirmation_keyboard(
    *, season_id: int, achievement_id: int
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🗑 Удалить",
        callback_data=HallOfFameDeleteCallback(
            action=HallOfFameDeleteAction.CONFIRM,
            season_id=season_id,
            achievement_id=achievement_id,
        ),
    )
    builder.button(
        text="⬅️ Назад",
        callback_data=HallOfFameDeleteCallback(
            action=HallOfFameDeleteAction.BACK_LIST,
            season_id=season_id,
            achievement_id=achievement_id,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=HallOfFameDeleteCallback(
            action=HallOfFameDeleteAction.CANCEL,
            season_id=season_id,
            achievement_id=achievement_id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def confirmation_keyboard(
    *,
    season_id: int,
    field: HallOfFameField,
    player_id: int,
    replacing: bool = False,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Заменить" if replacing else "✅ Сохранить",
        callback_data=HallOfFameConfirmCallback(
            action=HallOfFameConfirmAction.CONFIRM,
            season_id=season_id,
            field=field,
            player_id=player_id,
        ),
    )
    builder.button(
        text="⬅️ Назад",
        callback_data=HallOfFameConfirmCallback(
            action=HallOfFameConfirmAction.BACK,
            season_id=season_id,
            field=field,
            player_id=player_id,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=HallOfFameConfirmCallback(
            action=HallOfFameConfirmAction.CANCEL,
            season_id=season_id,
            field=field,
            player_id=player_id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def photo_prompt_keyboard(*, season_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="⬅️ Назад",
        callback_data=HallOfFamePhotoCallback(
            action=HallOfFamePhotoAction.BACK_MENU,
            season_id=season_id,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=HallOfFamePhotoCallback(
            action=HallOfFamePhotoAction.CANCEL,
            season_id=season_id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def photo_confirmation_keyboard(*, season_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Сохранить",
        callback_data=HallOfFamePhotoCallback(
            action=HallOfFamePhotoAction.SAVE,
            season_id=season_id,
        ),
    )
    builder.button(
        text="⬅️ Назад",
        callback_data=HallOfFamePhotoCallback(
            action=HallOfFamePhotoAction.BACK_MENU,
            season_id=season_id,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=HallOfFamePhotoCallback(
            action=HallOfFamePhotoAction.CANCEL,
            season_id=season_id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()
