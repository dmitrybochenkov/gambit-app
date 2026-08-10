import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from app.bot.telegram.keyboards import labels
from app.bot.telegram.keyboards.admin import panel as admin_panel_kb
from app.bot.telegram.texts.admin import panel as text
from app.services.access_policy import AdminAccessDeniedError
from app.services.user_access_service import user_access_service

logger = logging.getLogger(__name__)


router = Router(name="admin.panel")


@router.message(Command("admin"))
@router.message(F.text == labels.MAIN_ADMIN)
async def open_admin_panel(message: Message) -> None:
    if message.from_user is None:
        return

    try:
        admin_panel = await user_access_service.get_admin_panel_for_admin(message.from_user.id)
    except AdminAccessDeniedError:
        await message.answer(text.ACCESS_DENIED)
        return

    await message.answer(
        text.ADMIN_PANEL_WELCOME,
        reply_markup=admin_panel_kb.admin_panel_keyboard(admin_panel.admin),
    )


@router.message(F.text == labels.ADMIN_PANEL_ADMIN)
@router.message(F.text == labels.ADMIN_PANEL_BACK)
async def back_to_admin_panel(message: Message) -> None:
    if message.from_user is None:
        return

    try:
        admin_panel = await user_access_service.get_admin_panel_for_admin(message.from_user.id)
    except AdminAccessDeniedError:
        await message.answer(text.ACCESS_DENIED)
        return

    await message.answer(
        text.ADMIN_PANEL_WELCOME,
        reply_markup=admin_panel_kb.admin_panel_keyboard(admin_panel.admin),
    )
