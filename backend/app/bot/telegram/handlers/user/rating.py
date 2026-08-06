# ruff: noqa: F403,F405
from aiogram import Router

from app.bot.telegram.handlers.user.common import *  # noqa: F403

router = Router(name="user.rating")


@router.message(F.text == keyboards.MAIN_RATING)
async def show_rating_menu(message: Message) -> None:
    if message.from_user is None:
        return

    try:
        await user_service.require_active_user(message.from_user.id)
    except ActiveUserRequiredError:
        await message.answer(texts.user.RATING_UNAVAILABLE)
        return

    await message.answer(
        texts.user.RATING_MENU_PROMPT,
        reply_markup=keyboards.rating_keyboard(),
    )


@router.callback_query(keyboards.RatingCallback.filter())
async def show_rating(
    callback: CallbackQuery,
    callback_data: keyboards.RatingCallback,
) -> None:
    try:
        rating = await rating_service.get_rating_for_player(
            telegram_id=callback.from_user.id,
            kind=callback_data.kind,
        )
    except RatingNotAllowedError:
        await callback.answer(
            texts.user.RATING_ACTIVE_ONLY,
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
        page_size=keyboards.RATING_PAGE_SIZE,
    )
    await callback.answer()
    if callback.message is not None:
        try:
            await callback.message.edit_text(
                format_rating(rating.title, page, rating.current_player_id),
                reply_markup=keyboards.rating_page_keyboard(callback_data.kind, page),
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
            return index // keyboards.RATING_PAGE_SIZE
    return 0


@router.callback_query(keyboards.RatingCancelCallback.filter())
async def cancel_rating(
    callback: CallbackQuery,
    callback_data: keyboards.RatingCancelCallback,
) -> None:
    answer = (
        "Рейтинг закрыт" if callback_data.action == keyboards.RatingCancelAction.CLOSE else "Отмена"
    )
    await callback.answer(answer)
    if callback.message is None:
        return

    await _delete_message(callback.message)
    await callback.message.answer(answer)
