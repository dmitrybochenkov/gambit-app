from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from app.bot.telegram.keyboards.user import menu as user_menu_kb
from app.bot.telegram.texts.superadmin import administrators as administrator_text
from app.services.dto.users import UserView


class TelegramAdminPromotionNotificationDelivery:
    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def deliver(self, promoted_user: UserView) -> None:
        if promoted_user.telegram_id is None:
            return
        try:
            await self._bot.send_message(
                chat_id=promoted_user.telegram_id,
                text=administrator_text.ADMIN_ADDED_FOR_PLAYER,
                reply_markup=user_menu_kb.main_keyboard_after_role_update(promoted_user),
            )
        except (TelegramBadRequest, TelegramForbiddenError):
            pass
