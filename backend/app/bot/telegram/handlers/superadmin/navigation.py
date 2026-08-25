from aiogram.types import Message

from app.bot.telegram.keyboards.superadmin import panel as superadmin_panel_kb
from app.services.user_access_service import user_access_service


async def send_superadmin_panel(
    message: Message,
    *,
    superadmin_telegram_id: int,
    text: str,
) -> None:
    await user_access_service.get_superadmin_panel_for_superadmin(superadmin_telegram_id)
    await message.answer(
        text,
        reply_markup=superadmin_panel_kb.superadmin_panel_keyboard(),
    )
