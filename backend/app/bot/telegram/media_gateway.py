from io import BytesIO

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from app.services.media_gateway import MediaContent, MediaGatewayError


class AiogramTelegramMediaGateway:
    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def download_photo(self, source_reference: str) -> MediaContent:
        destination = BytesIO()
        try:
            await self._bot.download(source_reference, destination=destination)
        except TelegramAPIError as exc:
            raise MediaGatewayError from exc
        return MediaContent(data=destination.getvalue(), content_type="image/jpeg")
