from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from app.bot.telegram.formatters.statistics import profile as profile_fmt
from app.bot.telegram.handlers.user.shared import (
    delete_message as _delete_message,
)
from app.bot.telegram.keyboards import labels
from app.bot.telegram.keyboards.user import profile as user_profile_kb
from app.bot.telegram.texts.user import profile as text
from app.services.access_policy import ActiveUserRequiredError
from app.services.profile_service import ProfileNotAllowedError, profile_service
from app.services.user_service import (
    user_service,
)

router = Router(name="user.profile")


@router.message(F.text == labels.MAIN_PROFILE)
async def show_profile_menu(message: Message) -> None:
    if message.from_user is None:
        return

    try:
        await user_service.require_active_user(message.from_user.id)
    except ActiveUserRequiredError:
        await message.answer(text.PROFILE_UNAVAILABLE)
        return

    await message.answer(
        text.PROFILE_MENU_PROMPT,
        reply_markup=user_profile_kb.profile_keyboard(),
    )


@router.callback_query(user_profile_kb.ProfileCallback.filter())
async def show_profile(
    callback: CallbackQuery,
    callback_data: user_profile_kb.ProfileCallback,
) -> None:
    try:
        title, stats = await profile_service.get_profile_for_player(
            telegram_id=callback.from_user.id,
            kind=callback_data.kind,
        )
    except ProfileNotAllowedError:
        await callback.answer(
            text.PROFILE_ACTIVE_ONLY,
            show_alert=True,
        )
        return

    await callback.answer()
    if callback.message is not None:
        await _delete_message(callback.message)
        await callback.message.answer(profile_fmt.message(title, stats))


@router.callback_query(user_profile_kb.ProfileCancelCallback.filter())
async def cancel_profile(callback: CallbackQuery) -> None:
    await callback.answer("Отмена")
    if callback.message is None:
        return

    await _delete_message(callback.message)
    await callback.message.answer("Отмена")
