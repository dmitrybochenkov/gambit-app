from aiogram import F, Router
from aiogram.types import Message

from app.bot.telegram.formatters.statistics import hall_of_fame as hall_of_fame_fmt
from app.bot.telegram.keyboards import labels
from app.bot.telegram.photo_collage import build_photo_collage
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
        parse_mode="Markdown",
    )
    for season in seasons:
        await _send_hall_of_fame_season(message, season)


async def _send_hall_of_fame_season(message: Message, season: object) -> None:
    caption = hall_of_fame_fmt.season_caption(season)
    photos = [photo.telegram_file_id for photo in season.photos]
    if len(photos) == 1:
        await message.answer_photo(photos[0], caption=caption, parse_mode="Markdown")
    elif photos:
        collage = await build_photo_collage(message.bot, photos)
        await message.answer_photo(collage, caption=caption, parse_mode="Markdown")
    else:
        await message.answer(caption, parse_mode="Markdown")
