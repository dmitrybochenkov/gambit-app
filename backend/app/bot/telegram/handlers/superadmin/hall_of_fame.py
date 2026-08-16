import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.telegram.formatters import hall_of_fame as hall_fmt
from app.bot.telegram.handlers.admin.shared import (
    delete_callback_message as _delete_callback_message,
)
from app.bot.telegram.handlers.admin.shared import (
    delete_message_by_id as _delete_message_by_id,
)
from app.bot.telegram.handlers.user.shared import clean_text as _clean_text
from app.bot.telegram.keyboards import labels
from app.bot.telegram.keyboards.superadmin import hall_of_fame as hall_kb
from app.bot.telegram.keyboards.superadmin import panel as superadmin_panel_kb
from app.bot.telegram.message_edit import (
    edit_message_if_changed,
    edit_message_reply_markup_by_id_if_changed,
)
from app.bot.telegram.states import HallOfFameStates
from app.bot.telegram.texts.superadmin import hall_of_fame as text
from app.bot.telegram.texts.superadmin import panel as panel_text
from app.services.access_policy import AdminAccessDeniedError
from app.services.hall_of_fame_management_service import (
    HallOfFamePhotoRole,
    HallOfFameSeasonNotFoundError,
    hall_of_fame_management_service,
)
from app.services.pagination import pagination_service
from app.services.user_common import UserNotFoundError

logger = logging.getLogger(__name__)


router = Router(name="superadmin.hall_of_fame")


@router.message(F.text == labels.ADMIN_PANEL_HALL_OF_FAME)
async def show_hall_of_fame_management(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return
    await state.clear()
    try:
        seasons = await hall_of_fame_management_service.list_completed_seasons(message.from_user.id)
    except AdminAccessDeniedError:
        await message.answer(panel_text.INSUFFICIENT_RIGHTS)
        return
    page = pagination_service.paginate(seasons, page=0, page_size=hall_kb.PAGE_SIZE)
    await message.answer(
        hall_fmt.season_list(page),
        reply_markup=hall_kb.seasons_keyboard(page),
    )


@router.callback_query(hall_kb.HallOfFameSeasonCallback.filter())
async def select_hall_of_fame_season(
    callback: CallbackQuery,
    callback_data: hall_kb.HallOfFameSeasonCallback,
    state: FSMContext,
) -> None:
    try:
        if callback_data.action == hall_kb.HallOfFameSeasonAction.CANCEL:
            await _cancel(callback, state)
            return
        if callback_data.action == hall_kb.HallOfFameSeasonAction.PAGE:
            seasons = await hall_of_fame_management_service.list_completed_seasons(
                callback.from_user.id
            )
            page = pagination_service.paginate(
                seasons,
                page=callback_data.page,
                page_size=hall_kb.PAGE_SIZE,
            )
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=hall_fmt.season_list(page),
                    reply_markup=hall_kb.seasons_keyboard(page),
                )
            return
        entry = await hall_of_fame_management_service.get_season_hall_of_fame(
            callback.from_user.id,
            callback_data.season_id,
        )
    except AdminAccessDeniedError:
        await callback.answer(panel_text.INSUFFICIENT_RIGHTS, show_alert=True)
        return
    except HallOfFameSeasonNotFoundError:
        await callback.answer(text.HALL_OF_FAME_SEASON_NOT_FOUND, show_alert=True)
        return

    await state.clear()
    await callback.answer()
    if callback.message is not None:
        await edit_message_if_changed(
            callback.message,
            text=hall_fmt.season_card(entry),
            reply_markup=hall_kb.season_card_keyboard(
                entry=entry,
                page=callback_data.page,
            ),
            parse_mode="Markdown",
        )


@router.callback_query(hall_kb.HallOfFameCardCallback.filter())
async def select_hall_of_fame_card_action(
    callback: CallbackQuery,
    callback_data: hall_kb.HallOfFameCardCallback,
    state: FSMContext,
) -> None:
    if callback_data.action == hall_kb.HallOfFameCardAction.CANCEL:
        await _cancel(callback, state)
        return
    if callback_data.action == hall_kb.HallOfFameCardAction.BACK:
        await _show_season_list_callback(callback, callback_data.page, state)
        return

    if callback_data.action in {
        hall_kb.HallOfFameCardAction.CHAMPION_PHOTO,
        hall_kb.HallOfFameCardAction.KNOCKOUT_PHOTO,
    }:
        field = (
            hall_kb.HallOfFameField.CHAMPION
            if callback_data.action == hall_kb.HallOfFameCardAction.CHAMPION_PHOTO
            else hall_kb.HallOfFameField.KNOCKOUT
        )
        await _start_photo_flow(callback, callback_data.season_id, field, state)
        return

    field = (
        hall_kb.HallOfFameField.CHAMPION
        if callback_data.action == hall_kb.HallOfFameCardAction.CHOOSE_CHAMPION
        else hall_kb.HallOfFameField.KNOCKOUT
    )
    await state.clear()
    await state.set_state(HallOfFameStates.entering_player_name)
    await state.update_data(hall_season_id=callback_data.season_id, hall_field=field.value)
    await callback.answer()
    if callback.message is not None:
        await _delete_callback_message(callback)
        prompt = await callback.message.answer(
            hall_fmt.search_prompt(field),
            reply_markup=hall_kb.search_prompt_keyboard(
                season_id=callback_data.season_id,
                field=field,
            ),
        )
        await state.update_data(hall_prompt_message_id=prompt.message_id)


@router.message(HallOfFameStates.entering_player_name)
async def search_hall_of_fame_player(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return
    data = await state.get_data()
    season_id = int(data["hall_season_id"])
    field = hall_kb.HallOfFameField(str(data["hall_field"]))
    query = _clean_text(message.text or "")
    await _clear_search_prompt_markup(message, data)
    try:
        candidates = await hall_of_fame_management_service.search_players(
            message.from_user.id,
            query,
        )
    except AdminAccessDeniedError:
        await state.clear()
        await message.answer(panel_text.INSUFFICIENT_RIGHTS)
        return

    await state.update_data(hall_query=query)
    await message.answer(
        hall_fmt.search_results(candidates),
        reply_markup=hall_kb.search_results_keyboard(
            season_id=season_id,
            field=field,
            candidates=candidates,
        ),
    )


@router.callback_query(hall_kb.HallOfFameSearchCallback.filter())
async def select_hall_of_fame_candidate(
    callback: CallbackQuery,
    callback_data: hall_kb.HallOfFameSearchCallback,
    state: FSMContext,
) -> None:
    if callback_data.action == hall_kb.HallOfFameSearchAction.CANCEL:
        await _cancel(callback, state)
        return
    if callback_data.action == hall_kb.HallOfFameSearchAction.BACK:
        await _show_hall_card_callback(callback, callback_data.season_id, page=0, state=state)
        return
    try:
        player = await hall_of_fame_management_service.get_player(
            callback.from_user.id,
            callback_data.player_id,
        )
        entry = await hall_of_fame_management_service.get_season_hall_of_fame(
            callback.from_user.id,
            callback_data.season_id,
        )
    except AdminAccessDeniedError:
        await callback.answer(panel_text.INSUFFICIENT_RIGHTS, show_alert=True)
        return
    except (UserNotFoundError, HallOfFameSeasonNotFoundError):
        await callback.answer(text.HALL_OF_FAME_PLAYER_NOT_FOUND, show_alert=True)
        return

    await callback.answer()
    if callback.message is not None:
        await edit_message_if_changed(
            callback.message,
            text=hall_fmt.confirmation(
                field=callback_data.field,
                player=player.user,
                season_name=entry.season_name,
            ),
            reply_markup=hall_kb.confirmation_keyboard(
                season_id=callback_data.season_id,
                field=callback_data.field,
                player_id=callback_data.player_id,
            ),
            parse_mode="Markdown",
        )


@router.callback_query(hall_kb.HallOfFameConfirmCallback.filter())
async def confirm_hall_of_fame_player(
    callback: CallbackQuery,
    callback_data: hall_kb.HallOfFameConfirmCallback,
    state: FSMContext,
) -> None:
    if callback_data.action == hall_kb.HallOfFameConfirmAction.CANCEL:
        await _cancel(callback, state)
        return
    if callback_data.action == hall_kb.HallOfFameConfirmAction.BACK:
        await _show_candidate_list_from_state(callback, callback_data, state)
        return

    try:
        player = await hall_of_fame_management_service.get_player(
            callback.from_user.id,
            callback_data.player_id,
        )
        if callback_data.field == hall_kb.HallOfFameField.CHAMPION:
            entry = await hall_of_fame_management_service.set_champion(
                callback.from_user.id,
                callback_data.season_id,
                callback_data.player_id,
            )
            saved_text = text.saved_champion(player.user.display_name, entry.season_name)
        else:
            entry = await hall_of_fame_management_service.set_knockout_player(
                callback.from_user.id,
                callback_data.season_id,
                callback_data.player_id,
            )
            saved_text = text.saved_knockout(player.user.display_name, entry.season_name)
    except AdminAccessDeniedError:
        await callback.answer(panel_text.INSUFFICIENT_RIGHTS, show_alert=True)
        return
    except HallOfFameSeasonNotFoundError:
        await callback.answer(text.HALL_OF_FAME_SEASON_NOT_FOUND, show_alert=True)
        return
    except UserNotFoundError:
        await callback.answer(text.HALL_OF_FAME_PLAYER_NOT_FOUND, show_alert=True)
        return

    await state.clear()
    await callback.answer(saved_text)
    if callback.message is not None:
        await _delete_callback_message(callback)
        await callback.message.answer(saved_text)
        await callback.message.answer(
            hall_fmt.season_card(entry),
            reply_markup=hall_kb.season_card_keyboard(
                entry=entry,
                page=0,
            ),
            parse_mode="Markdown",
        )


async def _show_season_list_callback(
    callback: CallbackQuery,
    page_number: int,
    state: FSMContext,
) -> None:
    try:
        seasons = await hall_of_fame_management_service.list_completed_seasons(
            callback.from_user.id
        )
    except AdminAccessDeniedError:
        await callback.answer(panel_text.INSUFFICIENT_RIGHTS, show_alert=True)
        return
    page = pagination_service.paginate(seasons, page=page_number, page_size=hall_kb.PAGE_SIZE)
    await state.clear()
    await callback.answer()
    if callback.message is not None:
        await edit_message_if_changed(
            callback.message,
            text=hall_fmt.season_list(page),
            reply_markup=hall_kb.seasons_keyboard(page),
        )


async def _show_hall_card_callback(
    callback: CallbackQuery,
    season_id: int,
    *,
    page: int,
    state: FSMContext,
) -> None:
    try:
        entry = await hall_of_fame_management_service.get_season_hall_of_fame(
            callback.from_user.id,
            season_id,
        )
    except AdminAccessDeniedError:
        await callback.answer(panel_text.INSUFFICIENT_RIGHTS, show_alert=True)
        return
    except HallOfFameSeasonNotFoundError:
        await callback.answer(text.HALL_OF_FAME_SEASON_NOT_FOUND, show_alert=True)
        return
    await state.clear()
    await callback.answer()
    if callback.message is not None:
        await edit_message_if_changed(
            callback.message,
            text=hall_fmt.season_card(entry),
            reply_markup=hall_kb.season_card_keyboard(entry=entry, page=page),
            parse_mode="Markdown",
        )


async def _start_photo_flow(
    callback: CallbackQuery,
    season_id: int,
    field: hall_kb.HallOfFameField,
    state: FSMContext,
) -> None:
    try:
        entry = await hall_of_fame_management_service.get_season_hall_of_fame(
            callback.from_user.id,
            season_id,
        )
    except AdminAccessDeniedError:
        await callback.answer(panel_text.INSUFFICIENT_RIGHTS, show_alert=True)
        return
    except HallOfFameSeasonNotFoundError:
        await callback.answer(text.HALL_OF_FAME_SEASON_NOT_FOUND, show_alert=True)
        return
    await state.clear()
    await state.set_state(HallOfFameStates.collecting_photo)
    await state.update_data(
        hall_season_id=season_id,
        hall_field=field.value,
        hall_season_name=entry.season_name,
    )
    await callback.answer()
    if callback.message is not None:
        await _delete_callback_message(callback)
        prompt = await callback.message.answer(
            hall_fmt.photo_prompt(field=field, season_name=entry.season_name),
            reply_markup=hall_kb.photo_prompt_keyboard(season_id=season_id, field=field),
        )
        await state.update_data(hall_photo_prompt_message_id=prompt.message_id)


@router.message(HallOfFameStates.collecting_photo, F.photo)
async def collect_hall_of_fame_photo(message: Message, state: FSMContext) -> None:
    if message.from_user is None or not message.photo:
        return
    data = await state.get_data()
    season_id = int(data["hall_season_id"])
    field = hall_kb.HallOfFameField(str(data["hall_field"]))
    season_name = str(data["hall_season_name"])
    photo = message.photo[-1]
    await _clear_photo_prompt_message(message, data)
    await state.update_data(
        hall_photo_file_id=photo.file_id,
        hall_photo_file_unique_id=photo.file_unique_id,
        hall_photo_prompt_message_id=0,
    )
    await message.answer_photo(photo.file_id)
    await message.answer(
        hall_fmt.photo_confirmation(field=field, season_name=season_name),
        reply_markup=hall_kb.photo_confirmation_keyboard(season_id=season_id, field=field),
    )


@router.message(HallOfFameStates.collecting_photo)
async def reject_hall_of_fame_non_photo(message: Message) -> None:
    await message.answer("Пришли фотографию.")


@router.callback_query(hall_kb.HallOfFamePhotoCallback.filter())
async def select_hall_of_fame_photo_action(
    callback: CallbackQuery,
    callback_data: hall_kb.HallOfFamePhotoCallback,
    state: FSMContext,
) -> None:
    if callback_data.action == hall_kb.HallOfFamePhotoAction.CANCEL:
        await _cancel(callback, state)
        return
    if callback_data.action == hall_kb.HallOfFamePhotoAction.BACK:
        await _show_hall_card_callback(callback, callback_data.season_id, page=0, state=state)
        return
    data = await state.get_data()
    try:
        entry = await hall_of_fame_management_service.set_photo(
            callback.from_user.id,
            callback_data.season_id,
            role=HallOfFamePhotoRole(callback_data.field.value),
            telegram_file_id=str(data["hall_photo_file_id"]),
            telegram_file_unique_id=str(data["hall_photo_file_unique_id"]),
        )
    except KeyError:
        await callback.answer("Пришли фотографию.", show_alert=True)
        return
    except AdminAccessDeniedError:
        await callback.answer(panel_text.INSUFFICIENT_RIGHTS, show_alert=True)
        return
    except HallOfFameSeasonNotFoundError:
        await callback.answer(text.HALL_OF_FAME_SEASON_NOT_FOUND, show_alert=True)
        return
    await state.clear()
    await callback.answer("Фото сохранено.")
    if callback.message is not None:
        await _delete_callback_message(callback)
        await callback.message.answer(
            hall_fmt.season_card(entry),
            reply_markup=hall_kb.season_card_keyboard(entry=entry, page=0),
            parse_mode="Markdown",
        )


async def _show_candidate_list_from_state(
    callback: CallbackQuery,
    callback_data: hall_kb.HallOfFameConfirmCallback,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    query = str(data.get("hall_query") or "")
    try:
        candidates = await hall_of_fame_management_service.search_players(
            callback.from_user.id,
            query,
        )
    except AdminAccessDeniedError:
        await callback.answer(panel_text.INSUFFICIENT_RIGHTS, show_alert=True)
        return
    await callback.answer()
    if callback.message is not None:
        await edit_message_if_changed(
            callback.message,
            text=hall_fmt.search_results(candidates),
            reply_markup=hall_kb.search_results_keyboard(
                season_id=callback_data.season_id,
                field=callback_data.field,
                candidates=candidates,
            ),
        )


async def _cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer(text.HALL_OF_FAME_CANCELLED)
    if callback.message is not None:
        await _delete_callback_message(callback)
        await callback.message.answer(
            text.HALL_OF_FAME_CANCELLED,
            reply_markup=superadmin_panel_kb.superadmin_panel_keyboard(),
        )


async def _clear_search_prompt_markup(message: Message, data: dict[str, object]) -> None:
    prompt_message_id = int(data.get("hall_prompt_message_id") or 0)
    if prompt_message_id <= 0:
        return
    try:
        await edit_message_reply_markup_by_id_if_changed(
            message.bot,
            chat_id=message.chat.id,
            message_id=prompt_message_id,
            reply_markup=None,
        )
    except TelegramBadRequest:
        logger.info("Failed to clear Hall of Fame search prompt markup", exc_info=True)


async def _clear_photo_prompt_message(message: Message, data: dict[str, object]) -> None:
    prompt_message_id = int(data.get("hall_photo_prompt_message_id") or 0)
    if prompt_message_id <= 0:
        return
    await _delete_message_by_id(message, prompt_message_id)
