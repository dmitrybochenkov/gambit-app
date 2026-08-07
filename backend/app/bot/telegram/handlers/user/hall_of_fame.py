from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from app.bot.telegram.formatters.statistics import hall_of_fame as hall_of_fame_fmt
from app.bot.telegram.handlers.user.shared import (
    delete_message as _delete_message,
)
from app.bot.telegram.keyboards import labels
from app.bot.telegram.keyboards.user import history as user_history_kb
from app.bot.telegram.texts.user import hall_of_fame as text
from app.services.user_statistics_service import (
    HallOfFameNotAllowedError,
    user_statistics_service,
)

router = Router(name="user.hall_of_fame")


@router.message(F.text == labels.MAIN_HALL_OF_FAME)
async def show_hall_of_fame(message: Message) -> None:
    if message.from_user is None:
        return

    try:
        seasons = await user_statistics_service.get_hall_of_fame(message.from_user.id)
    except HallOfFameNotAllowedError:
        await message.answer(text.HALL_OF_FAME_UNAVAILABLE)
        return

    await message.answer(
        hall_of_fame_fmt.message(seasons),
        reply_markup=user_history_kb.hall_of_fame_keyboard(),
        parse_mode="Markdown",
    )


@router.callback_query(user_history_kb.HallOfFameCallback.filter())
async def close_hall_of_fame(callback: CallbackQuery) -> None:
    await callback.answer(text.HALL_OF_FAME_CLOSED)
    if callback.message is not None:
        await _delete_message(callback.message)
