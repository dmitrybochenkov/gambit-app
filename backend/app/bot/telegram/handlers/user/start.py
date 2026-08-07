from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, ReplyKeyboardRemove

from app.bot.telegram.handlers.user.shared import (
    send_registration_intro as _send_registration_intro,
)
from app.bot.telegram.keyboards import labels
from app.bot.telegram.keyboards.user import menu as user_menu_kb
from app.bot.telegram.texts.user import registration as registration_text
from app.bot.telegram.texts.user import start as text
from app.services.access_policy import ActiveUserRequiredError
from app.services.dto import UserStartStatusView
from app.services.user_service import (
    user_service,
)

router = Router(name="user.start")


@router.message(CommandStart())
async def start_command(message: Message, state: FSMContext) -> None:
    await state.clear()
    if message.from_user is None:
        return

    start_view = await user_service.get_start_view(message.from_user.id)
    if start_view.status == UserStartStatusView.PENDING_REGISTRATION:
        await message.answer(
            registration_text.REGISTRATION_PENDING,
            reply_markup=ReplyKeyboardRemove(),
        )
        return
    if start_view.status == UserStartStatusView.NEEDS_REGISTRATION:
        await _send_registration_intro(message, state)
        return
    if start_view.status == UserStartStatusView.BLOCKED:
        await message.answer(
            text.BOT_ACCESS_BLOCKED,
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    user = start_view.required_user
    await message.answer(
        text.welcome_back(user.display_name),
        reply_markup=user_menu_kb.main_keyboard_for_player(user),
    )


@router.message(F.text == labels.MAIN_ADDRESS)
async def show_club_address(message: Message) -> None:
    if message.from_user is None:
        return

    try:
        await user_service.require_active_user(message.from_user.id)
    except ActiveUserRequiredError:
        await message.answer(text.ADDRESS_UNAVAILABLE)
        return

    await message.answer(text.CLUB_ADDRESS)
