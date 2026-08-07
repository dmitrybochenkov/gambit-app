import re
from datetime import date

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message

from app.bot.telegram.keyboards.admin.results import AdminResultField
from app.services.result_service import ResultField

RESULT_SUMMARY_PARSE_MODE = "Markdown"


async def delete_callback_message(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest:
            pass


async def delete_message_by_id(message: Message, message_id: int) -> None:
    if message_id <= 0:
        return
    try:
        await message.bot.delete_message(
            chat_id=message.chat.id,
            message_id=message_id,
        )
    except TelegramBadRequest:
        pass


def parse_admin_date(value: str) -> date:
    match = re.fullmatch(r"(\d{1,2})\.(\d{2})\.(\d{4})", value.strip())
    if match is None:
        raise ValueError
    day, month, year = (int(part) for part in match.groups())
    return date(year, month, day)


def parse_result_manual_value(value: str, *, field: AdminResultField) -> int:
    result = parse_nonnegative_int(value)
    if field == AdminResultField.PLACE and result not in {1, 2, 3, 4, 5}:
        raise ValueError
    return result


def result_field_name(field: AdminResultField) -> str:
    return {
        AdminResultField.KNOCKOUTS: "🥊",
        AdminResultField.BIG_KNOCKOUTS: "👑🥊",
        AdminResultField.BONUS: "бонус",
        AdminResultField.PLACE: "место",
    }[field]


def to_result_field(field: AdminResultField) -> ResultField:
    return ResultField(field.value)


def parse_nonnegative_int(value: str) -> int:
    normalized = re.sub(r"\s+", "", value)
    if not normalized.isdecimal():
        raise ValueError
    return int(normalized)
