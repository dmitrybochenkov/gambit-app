import re

from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.telegram.keyboards.user import registration as user_registration_kb
from app.bot.telegram.texts.user import registration as registration_text


def clean_text(value: str) -> str:
    return " ".join(value.split())


def is_valid_display_name(value: str) -> bool:
    return 1 <= len(value) <= 255 and re.fullmatch(r"[\w\s.@-]+", value) is not None


async def send_registration_intro(message: Message, state: FSMContext) -> None:
    await message.answer(
        registration_text.REGISTRATION_GREETING,
        reply_markup=user_registration_kb.registration_start_keyboard(),
    )
    await state.set_state(None)


async def delete_message(message: Message) -> None:
    try:
        await message.delete()
    except TelegramBadRequest:
        pass


async def edit_history_message(
    callback: CallbackQuery,
    text: str,
    reply_markup: object,
    parse_mode: str | None = None,
) -> None:
    await callback.answer()
    if callback.message is None:
        return
    try:
        await callback.message.edit_text(
            text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
    except TelegramBadRequest:
        pass


async def delete_prompt_and_input(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    prompt_message_id = data.get("prompt_message_id")
    if prompt_message_id:
        try:
            await message.bot.delete_message(
                chat_id=message.chat.id,
                message_id=prompt_message_id,
            )
        except TelegramBadRequest:
            pass

    await delete_message(message)
    await state.update_data(prompt_message_id=None)


async def send_input_prompt(
    message: Message,
    state: FSMContext,
    text: str,
) -> None:
    prompt = await message.answer(text)
    await state.update_data(prompt_message_id=prompt.message_id)
