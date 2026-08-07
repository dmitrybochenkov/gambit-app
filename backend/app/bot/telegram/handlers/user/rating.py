from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message

from app.bot.telegram.formatters.statistics import rating as rating_fmt
from app.bot.telegram.handlers.user.shared import (
    delete_message as _delete_message,
)
from app.bot.telegram.keyboards import labels
from app.bot.telegram.keyboards.user import rating as user_rating_kb
from app.bot.telegram.texts.user import rating as text
from app.services.access_policy import ActiveUserRequiredError
from app.services.pagination import pagination_service
from app.services.rating_service import RatingNotAllowedError, rating_service
from app.services.user_access_service import user_access_service

router = Router(name="user.rating")


@router.message(F.text == labels.MAIN_RATING)
async def show_rating_menu(message: Message) -> None:
    if message.from_user is None:
        return

    try:
        await user_access_service.require_active_user(message.from_user.id)
    except ActiveUserRequiredError:
        await message.answer(text.RATING_UNAVAILABLE)
        return

    await message.answer(
        text.RATING_MENU_PROMPT,
        reply_markup=user_rating_kb.rating_keyboard(),
    )


@router.callback_query(user_rating_kb.RatingCallback.filter())
async def show_rating(
    callback: CallbackQuery,
    callback_data: user_rating_kb.RatingCallback,
) -> None:
    try:
        rating = await rating_service.get_rating_for_player(
            telegram_id=callback.from_user.id,
            kind=callback_data.kind,
        )
    except RatingNotAllowedError:
        await callback.answer(
            text.RATING_ACTIVE_ONLY,
            show_alert=True,
        )
        return

    page_number = rating_page_for_player(
        rating.rows,
        current_player_id=rating.current_player_id,
        requested_page=callback_data.page,
    )
    page = pagination_service.paginate(
        rating.rows,
        page=page_number,
        page_size=user_rating_kb.RATING_PAGE_SIZE,
    )
    await callback.answer()
    if callback.message is not None:
        try:
            await callback.message.edit_text(
                rating_fmt.message(rating.title, page, rating.current_player_id),
                reply_markup=user_rating_kb.rating_page_keyboard(callback_data.kind, page),
                parse_mode="Markdown",
            )
        except TelegramBadRequest:
            pass


def rating_page_for_player(
    rows: list[object],
    *,
    current_player_id: int,
    requested_page: int,
) -> int:
    if requested_page >= 0:
        return requested_page
    for index, row in enumerate(rows):
        if getattr(row, "player_id", None) == current_player_id:
            return index // user_rating_kb.RATING_PAGE_SIZE
    return 0


@router.callback_query(user_rating_kb.RatingCancelCallback.filter())
async def cancel_rating(
    callback: CallbackQuery,
    callback_data: user_rating_kb.RatingCancelCallback,
) -> None:
    answer = (
        "Рейтинг закрыт"
        if callback_data.action == user_rating_kb.RatingCancelAction.CLOSE
        else "Отмена"
    )
    await callback.answer(answer)
    if callback.message is None:
        return

    await _delete_message(callback.message)
    await callback.message.answer(answer)
