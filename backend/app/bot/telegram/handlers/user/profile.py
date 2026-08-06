# ruff: noqa: F403,F405
from aiogram import Router

from app.bot.telegram.handlers.user.common import *  # noqa: F403

router = Router(name="user.profile")


@router.message(F.text == keyboards.MAIN_PROFILE)
async def show_profile_menu(message: Message) -> None:
    if message.from_user is None:
        return

    try:
        await user_service.require_active_user(message.from_user.id)
    except ActiveUserRequiredError:
        await message.answer(texts.user.PROFILE_UNAVAILABLE)
        return

    await message.answer(
        texts.user.PROFILE_MENU_PROMPT,
        reply_markup=keyboards.profile_keyboard(),
    )


@router.callback_query(keyboards.ProfileCallback.filter())
async def show_profile(
    callback: CallbackQuery,
    callback_data: keyboards.ProfileCallback,
) -> None:
    try:
        title, stats = await profile_service.get_profile_for_player(
            telegram_id=callback.from_user.id,
            kind=callback_data.kind,
        )
    except ProfileNotAllowedError:
        await callback.answer(
            texts.user.PROFILE_ACTIVE_ONLY,
            show_alert=True,
        )
        return

    await callback.answer()
    if callback.message is not None:
        await _delete_message(callback.message)
        await callback.message.answer(format_profile(title, stats))


@router.callback_query(keyboards.ProfileCancelCallback.filter())
async def cancel_profile(callback: CallbackQuery) -> None:
    await callback.answer("Отмена")
    if callback.message is None:
        return

    await _delete_message(callback.message)
    await callback.message.answer("Отмена")
