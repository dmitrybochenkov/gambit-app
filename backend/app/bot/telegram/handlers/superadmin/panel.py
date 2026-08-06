# ruff: noqa: F403,F405
from aiogram import Router

from app.bot.telegram.handlers.admin.common import *  # noqa: F403

router = Router(name="superadmin.panel")


@router.message(F.text == keyboards.ADMIN_PANEL_SUPERADMIN)
async def open_superadmin_panel(message: Message) -> None:
    if message.from_user is None:
        return

    try:
        await user_service.require_superadmin(message.from_user.id)
    except AdminAccessDeniedError:
        await message.answer(texts.admin.INSUFFICIENT_RIGHTS)
        return

    await message.answer(
        texts.admin.SUPERADMIN_PANEL_WELCOME,
        reply_markup=keyboards.superadmin_panel_keyboard(),
    )
