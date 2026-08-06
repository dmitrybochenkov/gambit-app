# ruff: noqa: F403,F405
from aiogram import Router

from app.bot.telegram.handlers.user.common import *  # noqa: F403

router = Router(name="user.hall_of_fame")


@router.message(F.text == keyboards.MAIN_HALL_OF_FAME)
async def show_hall_of_fame(message: Message) -> None:
    if message.from_user is None:
        return

    try:
        seasons = await user_statistics_service.get_hall_of_fame(message.from_user.id)
    except HallOfFameNotAllowedError:
        await message.answer(texts.user.HALL_OF_FAME_UNAVAILABLE)
        return

    await message.answer(
        format_hall_of_fame(seasons),
        reply_markup=keyboards.hall_of_fame_keyboard(),
        parse_mode="Markdown",
    )


@router.callback_query(keyboards.HallOfFameCallback.filter())
async def close_hall_of_fame(callback: CallbackQuery) -> None:
    await callback.answer(texts.user.HALL_OF_FAME_CLOSED)
    if callback.message is not None:
        await _delete_message(callback.message)
