# ruff: noqa: F403,F405
from aiogram import Router

from app.bot.telegram.handlers.admin.common import *  # noqa: F403

router = Router(name="admin.panel")


@router.message(Command("admin"))
@router.message(F.text == keyboards.MAIN_ADMIN)
async def open_admin_panel(message: Message) -> None:
    if message.from_user is None:
        return

    try:
        admin_panel = await user_service.get_admin_panel_for_admin(message.from_user.id)
    except AdminAccessDeniedError:
        await message.answer(texts.admin.ACCESS_DENIED)
        return

    await message.answer(
        texts.admin.ADMIN_PANEL_WELCOME,
        reply_markup=keyboards.admin_panel_keyboard(admin_panel.admin),
    )


@router.message(F.text == keyboards.ADMIN_PANEL_BACK)
async def back_to_admin_panel(message: Message) -> None:
    if message.from_user is None:
        return

    try:
        admin_panel = await user_service.get_admin_panel_for_admin(message.from_user.id)
    except AdminAccessDeniedError:
        await message.answer(texts.admin.ACCESS_DENIED)
        return

    await message.answer(
        texts.admin.ADMIN_PANEL_WELCOME,
        reply_markup=keyboards.admin_panel_keyboard(admin_panel.admin),
    )
