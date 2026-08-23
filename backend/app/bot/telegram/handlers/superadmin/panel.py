import logging

from aiogram import F, Router
from aiogram.types import Message

from app.bot.telegram.keyboards import labels
from app.bot.telegram.keyboards.superadmin import panel as superadmin_panel_kb
from app.bot.telegram.texts.superadmin import panel as panel_text
from app.services.access_policy import AdminAccessDeniedError
from app.services.user_access_service import user_access_service

logger = logging.getLogger(__name__)


router = Router(name="superadmin.panel")


@router.message(F.text == labels.ADMIN_PANEL_SUPERADMIN)
async def open_superadmin_panel(message: Message) -> None:
    if message.from_user is None:
        return

    try:
        panel = await user_access_service.get_superadmin_panel_for_superadmin(message.from_user.id)
    except AdminAccessDeniedError:
        await message.answer(panel_text.INSUFFICIENT_RIGHTS)
        return

    await message.answer(
        panel_text.SUPERADMIN_PANEL_WELCOME,
        reply_markup=superadmin_panel_kb.superadmin_panel_keyboard(
            panel.active_telegram_users_count,
        ),
    )
