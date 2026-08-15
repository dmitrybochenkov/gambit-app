import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, Message

from app.bot.telegram.formatters import results as result_fmt

PHOTO_ALBUM_REFRESH_DEBOUNCE_SECONDS = 0.35


@dataclass(frozen=True)
class PhotoControlContext:
    tournament_id: int
    control_message_id_key: str
    reply_markup: InlineKeyboardMarkup


_album_refresh_tasks: dict[tuple[int, int, str], asyncio.Task[None]] = {}


async def send_photo_control_message(
    message: Message,
    state: FSMContext,
    context: PhotoControlContext,
    *,
    photo_count: int,
    limit_reached: bool = False,
) -> Message:
    sent = await message.answer(
        result_fmt.photo_upload_prompt(photo_count, limit_reached=limit_reached),
        reply_markup=context.reply_markup,
    )
    await state.update_data(**{context.control_message_id_key: sent.message_id})
    return sent


async def refresh_photo_control_message(
    message: Message,
    state: FSMContext,
    context: PhotoControlContext,
    *,
    photo_count: int,
    limit_reached: bool = False,
) -> Message:
    await delete_current_photo_control_message(message, state, context)
    return await send_photo_control_message(
        message,
        state,
        context,
        photo_count=photo_count,
        limit_reached=limit_reached,
    )


async def delete_current_photo_control_message(
    message: Message,
    state: FSMContext,
    context: PhotoControlContext,
) -> None:
    data = await state.get_data()
    message_id = data.get(context.control_message_id_key)
    if isinstance(message_id, int):
        from app.bot.telegram.handlers.admin.shared import delete_message_by_id

        await delete_message_by_id(message, message_id)


def schedule_album_photo_control_refresh(
    message: Message,
    state: FSMContext,
    context: PhotoControlContext,
    *,
    count_provider: Callable[[], Awaitable[int]],
    limit_reached: bool,
) -> None:
    media_group_id = message.media_group_id
    if not media_group_id:
        return
    key = (message.chat.id, context.tournament_id, media_group_id)
    existing = _album_refresh_tasks.pop(key, None)
    if existing is not None:
        existing.cancel()
    _album_refresh_tasks[key] = asyncio.create_task(
        _debounced_album_refresh(
            key,
            message,
            state,
            context,
            count_provider=count_provider,
            limit_reached=limit_reached,
        )
    )


async def _debounced_album_refresh(
    key: tuple[int, int, str],
    message: Message,
    state: FSMContext,
    context: PhotoControlContext,
    *,
    count_provider: Callable[[], Awaitable[int]],
    limit_reached: bool,
) -> None:
    try:
        await asyncio.sleep(PHOTO_ALBUM_REFRESH_DEBOUNCE_SECONDS)
        await refresh_photo_control_message(
            message,
            state,
            context,
            photo_count=await count_provider(),
            limit_reached=limit_reached,
        )
    except asyncio.CancelledError:
        raise
    finally:
        current = _album_refresh_tasks.get(key)
        if current is asyncio.current_task():
            _album_refresh_tasks.pop(key, None)
