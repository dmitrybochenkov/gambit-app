# ruff: noqa: F403,F405
from aiogram import Router

from app.bot.telegram.handlers.user.common import *  # noqa: F403

router = Router(name="user.start")


@router.message(CommandStart())
async def start_command(message: Message, state: FSMContext) -> None:
    await state.clear()
    if message.from_user is None:
        return

    start_view = await user_service.get_start_view(message.from_user.id)
    if start_view.status == UserStartStatusView.PENDING_REGISTRATION:
        await message.answer(
            texts.user.REGISTRATION_PENDING,
            reply_markup=ReplyKeyboardRemove(),
        )
        return
    if start_view.status == UserStartStatusView.NEEDS_REGISTRATION:
        await _send_registration_intro(message, state)
        return
    if start_view.status == UserStartStatusView.BLOCKED:
        await message.answer(
            texts.user.BOT_ACCESS_BLOCKED,
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    user = start_view.required_user
    await message.answer(
        texts.user.welcome_back(user.display_name),
        reply_markup=keyboards.main_keyboard_for_player(user),
    )


@router.message(F.text == keyboards.MAIN_ADDRESS)
async def show_club_address(message: Message) -> None:
    if message.from_user is None:
        return

    try:
        await user_service.require_active_user(message.from_user.id)
    except ActiveUserRequiredError:
        await message.answer(texts.user.ADDRESS_UNAVAILABLE)
        return

    await message.answer(texts.user.CLUB_ADDRESS)
