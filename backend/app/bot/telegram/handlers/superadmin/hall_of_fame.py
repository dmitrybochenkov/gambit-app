import logging
from datetime import date

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.telegram.formatters import hall_of_fame as hall_fmt
from app.bot.telegram.handlers.admin.shared import (
    delete_callback_message as _delete_callback_message,
)
from app.bot.telegram.handlers.superadmin.navigation import send_superadmin_panel
from app.bot.telegram.handlers.user.shared import clean_text as _clean_text
from app.bot.telegram.keyboards import labels
from app.bot.telegram.keyboards.superadmin import hall_of_fame as hall_kb
from app.bot.telegram.message_edit import (
    edit_message_if_changed,
    edit_message_reply_markup_by_id_if_changed,
)
from app.bot.telegram.states import HallOfFameStates
from app.bot.telegram.texts.superadmin import hall_of_fame as text
from app.bot.telegram.texts.superadmin import panel as panel_text
from app.common.clock import club_clock
from app.db.models.enums import HallOfFameAchievementKind
from app.domain.hall_of_fame import SINGLETON_ACHIEVEMENT_KINDS
from app.services.access_policy import AdminAccessDeniedError
from app.services.hall_of_fame_management_service import (
    HallOfFameAchievementNotFoundError,
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
        seasons = await hall_of_fame_management_service.list_seasons(message.from_user.id)
    except AdminAccessDeniedError:
        await message.answer(panel_text.INSUFFICIENT_RIGHTS)
        return
    page = pagination_service.paginate(seasons, page=0, page_size=hall_kb.PAGE_SIZE)
    await message.answer(hall_fmt.season_list(page), reply_markup=hall_kb.seasons_keyboard(page))


@router.callback_query(hall_kb.HallOfFameSeasonCallback.filter())
async def select_hall_of_fame_season(
    callback: CallbackQuery, callback_data: hall_kb.HallOfFameSeasonCallback, state: FSMContext
) -> None:
    if callback_data.action == hall_kb.HallOfFameSeasonAction.CANCEL:
        await _cancel(callback, state)
    elif callback_data.action == hall_kb.HallOfFameSeasonAction.PAGE:
        await _show_season_list_callback(callback, callback_data.page, state)
    else:
        await _show_hall_card_callback(
            callback, callback_data.season_id, page=callback_data.page, state=state
        )


@router.callback_query(hall_kb.HallOfFameCardCallback.filter())
async def select_hall_of_fame_card_action(
    callback: CallbackQuery, callback_data: hall_kb.HallOfFameCardCallback, state: FSMContext
) -> None:
    if callback_data.action == hall_kb.HallOfFameCardAction.CANCEL:
        await _cancel(callback, state)
        return
    if callback_data.action == hall_kb.HallOfFameCardAction.BACK:
        await _show_season_list_callback(callback, callback_data.page, state)
        return
    if callback_data.action == hall_kb.HallOfFameCardAction.BACK_HUB:
        await _show_hall_card_callback(
            callback, callback_data.season_id, page=callback_data.page, state=state
        )
        return
    if callback_data.action == hall_kb.HallOfFameCardAction.PHOTOS:
        await state.update_data(hall_page=callback_data.page)
        await _show_photo_menu(callback, callback_data.season_id)
        return
    if callback_data.action == hall_kb.HallOfFameCardAction.ACHIEVEMENTS:
        await _show_achievements_menu(callback, callback_data.season_id, callback_data.page, state)
        return
    if callback_data.action == hall_kb.HallOfFameCardAction.DELETE_ACHIEVEMENT:
        await _show_delete_menu(callback, callback_data.season_id, state)
        return
    try:
        entry = await hall_of_fame_management_service.get_season_hall_of_fame(
            callback.from_user.id, callback_data.season_id
        )
    except HallOfFameSeasonNotFoundError:
        await callback.answer(text.HALL_OF_FAME_SEASON_NOT_FOUND, show_alert=True)
        return
    await state.clear()
    await state.set_state(HallOfFameStates.entering_awarded_at)
    await state.update_data(
        hall_season_id=callback_data.season_id,
        hall_field=callback_data.kind.value,
        hall_page=callback_data.page,
    )
    await callback.answer()
    if callback.message is not None:
        await edit_message_if_changed(
            callback.message,
            text=hall_fmt.date_prompt(entry, callback_data.kind),
            reply_markup=hall_kb.date_prompt_keyboard(
                season_id=callback_data.season_id,
                field=callback_data.kind,
                today_label=club_clock.today().strftime("%d.%m.%Y"),
            ),
            parse_mode="Markdown",
        )
        await state.update_data(
            hall_date_prompt_chat_id=callback.message.chat.id,
            hall_date_prompt_message_id=callback.message.message_id,
        )


@router.message(HallOfFameStates.entering_awarded_at)
async def enter_hall_of_fame_awarded_at(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return
    try:
        awarded_at = date.fromisoformat("-".join(reversed((message.text or "").strip().split("."))))
    except ValueError:
        await message.answer("Введи дату в формате ДД.ММ.ГГГГ.")
        return
    await _deactivate_message_from_state(
        message,
        state,
        chat_key="hall_date_prompt_chat_id",
        message_key="hall_date_prompt_message_id",
    )
    await _start_player_search(message, state, awarded_at, actor_telegram_id=message.from_user.id)


@router.callback_query(hall_kb.HallOfFameDateCallback.filter())
async def select_hall_of_fame_date_action(
    callback: CallbackQuery, callback_data: hall_kb.HallOfFameDateCallback, state: FSMContext
) -> None:
    if callback_data.action == hall_kb.HallOfFameDateAction.CANCEL:
        await _cancel(callback, state)
        return
    if callback_data.action == hall_kb.HallOfFameDateAction.BACK:
        data = await state.get_data()
        await _show_achievements_menu(
            callback, callback_data.season_id, int(data.get("hall_page") or 0), state
        )
        return
    data = await state.get_data()
    if await state.get_state() != HallOfFameStates.entering_awarded_at or not _wizard_state_matches(
        data, callback_data.season_id, callback_data.field
    ):
        await callback.answer("Этот шаг устарел. Открой награду заново.", show_alert=True)
        return
    if callback.message is not None:
        await callback.answer()
        await _edit_player_name_step(
            callback.message,
            state,
            club_clock.today(),
            actor_telegram_id=callback.from_user.id,
        )


async def _start_player_search(
    message: Message,
    state: FSMContext,
    awarded_at: date,
    *,
    actor_telegram_id: int,
) -> None:
    data = await state.get_data()
    field = hall_kb.HallOfFameField(str(data["hall_field"]))
    entry = await hall_of_fame_management_service.get_season_hall_of_fame(
        actor_telegram_id, int(data["hall_season_id"])
    )
    await state.update_data(hall_awarded_at=awarded_at.isoformat())
    await state.set_state(HallOfFameStates.entering_player_name)
    prompt = await message.answer(
        hall_fmt.player_prompt(entry, field, awarded_at),
        reply_markup=hall_kb.search_prompt_keyboard(
            season_id=int(data["hall_season_id"]), field=field
        ),
    )
    if prompt is not None and getattr(prompt, "chat", None) is not None:
        await state.update_data(
            hall_prompt_chat_id=prompt.chat.id,
            hall_prompt_message_id=prompt.message_id,
        )


async def _edit_player_name_step(
    message: Message,
    state: FSMContext,
    awarded_at: date,
    *,
    actor_telegram_id: int,
) -> None:
    data = await state.get_data()
    season_id = int(data["hall_season_id"])
    field = hall_kb.HallOfFameField(str(data["hall_field"]))
    entry = await hall_of_fame_management_service.get_season_hall_of_fame(
        actor_telegram_id, season_id
    )
    await state.update_data(
        hall_awarded_at=awarded_at.isoformat(),
        hall_prompt_chat_id=message.chat.id,
        hall_prompt_message_id=message.message_id,
    )
    await state.set_state(HallOfFameStates.entering_player_name)
    await edit_message_if_changed(
        message,
        text=hall_fmt.player_prompt(entry, field, awarded_at),
        reply_markup=hall_kb.search_prompt_keyboard(season_id=season_id, field=field),
        parse_mode="Markdown",
    )


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
            message.from_user.id, query
        )
    except AdminAccessDeniedError:
        await state.clear()
        await message.answer(panel_text.INSUFFICIENT_RIGHTS)
        return
    await state.update_data(hall_query=query)
    await state.set_state(HallOfFameStates.selecting_player)
    await message.answer(
        hall_fmt.search_results(candidates),
        reply_markup=hall_kb.search_results_keyboard(
            season_id=season_id, field=field, candidates=candidates
        ),
    )


@router.callback_query(hall_kb.HallOfFameSearchCallback.filter())
async def select_hall_of_fame_candidate(
    callback: CallbackQuery, callback_data: hall_kb.HallOfFameSearchCallback, state: FSMContext
) -> None:
    if callback_data.action == hall_kb.HallOfFameSearchAction.CANCEL:
        await _cancel(callback, state)
        return
    if callback_data.action == hall_kb.HallOfFameSearchAction.BACK_DATE:
        await _show_date_step(callback, callback_data.season_id, callback_data.field, state)
        return
    if callback_data.action == hall_kb.HallOfFameSearchAction.BACK_NAME:
        await _show_player_name_step(callback, callback_data.season_id, callback_data.field, state)
        return
    data = await state.get_data()
    if await state.get_state() != HallOfFameStates.selecting_player or not _wizard_state_matches(
        data, callback_data.season_id, callback_data.field
    ):
        await callback.answer("Этот шаг устарел. Открой награду заново.", show_alert=True)
        return
    try:
        player = await hall_of_fame_management_service.get_player(
            callback.from_user.id, callback_data.player_id
        )
        entry = await hall_of_fame_management_service.get_season_hall_of_fame(
            callback.from_user.id, callback_data.season_id
        )
    except AdminAccessDeniedError:
        await callback.answer(panel_text.INSUFFICIENT_RIGHTS, show_alert=True)
        return
    except (UserNotFoundError, HallOfFameSeasonNotFoundError):
        await callback.answer(text.HALL_OF_FAME_PLAYER_NOT_FOUND, show_alert=True)
        return
    kind = HallOfFameAchievementKind(callback_data.field.value)
    existing = (
        next((item for item in entry.achievements if item.kind == kind), None)
        if kind in SINGLETON_ACHIEVEMENT_KINDS
        else None
    )
    await state.set_state(HallOfFameStates.confirming_achievement)
    await callback.answer()
    if callback.message is not None:
        await edit_message_if_changed(
            callback.message,
            text=hall_fmt.achievement_confirmation(
                entry=entry,
                field=callback_data.field,
                player=player.user,
                awarded_at=date.fromisoformat(str(data["hall_awarded_at"])),
                existing=existing,
            ),
            reply_markup=hall_kb.confirmation_keyboard(
                season_id=callback_data.season_id,
                field=callback_data.field,
                player_id=callback_data.player_id,
                replacing=existing is not None,
            ),
            parse_mode="Markdown",
        )


@router.callback_query(hall_kb.HallOfFameConfirmCallback.filter())
async def confirm_hall_of_fame_player(
    callback: CallbackQuery, callback_data: hall_kb.HallOfFameConfirmCallback, state: FSMContext
) -> None:
    if callback_data.action == hall_kb.HallOfFameConfirmAction.CANCEL:
        await _cancel(callback, state)
        return
    if callback_data.action == hall_kb.HallOfFameConfirmAction.BACK:
        await _show_candidate_list_from_state(callback, callback_data, state)
        return
    data = await state.get_data()
    if (
        await state.get_state() != HallOfFameStates.confirming_achievement
        or not _wizard_state_matches(data, callback_data.season_id, callback_data.field)
    ):
        await callback.answer("Этот шаг устарел. Открой награду заново.", show_alert=True)
        return
    try:
        entry = await hall_of_fame_management_service.set_achievement(
            callback.from_user.id,
            callback_data.season_id,
            callback_data.player_id,
            HallOfFameAchievementKind(callback_data.field.value),
            date.fromisoformat(str(data["hall_awarded_at"])),
        )
    except AdminAccessDeniedError:
        await callback.answer(panel_text.INSUFFICIENT_RIGHTS, show_alert=True)
        return
    except (HallOfFameSeasonNotFoundError, UserNotFoundError):
        await callback.answer(text.HALL_OF_FAME_SEASON_NOT_FOUND, show_alert=True)
        return
    page = int(data.get("hall_page") or 0)
    await state.clear()
    await state.update_data(hall_page=page)
    await callback.answer("Достижение сохранено.")
    if callback.message is not None:
        await edit_message_if_changed(
            callback.message,
            text=hall_fmt.achievements_menu(entry),
            reply_markup=hall_kb.achievements_keyboard(entry=entry, page=page),
            parse_mode="Markdown",
        )


@router.callback_query(hall_kb.HallOfFameDeleteCallback.filter())
async def select_hall_of_fame_delete_action(
    callback: CallbackQuery,
    callback_data: hall_kb.HallOfFameDeleteCallback,
    state: FSMContext,
) -> None:
    if callback_data.action == hall_kb.HallOfFameDeleteAction.CANCEL:
        await _cancel(callback, state)
        return
    if callback_data.action == hall_kb.HallOfFameDeleteAction.BACK_MENU:
        data = await state.get_data()
        await _show_achievements_menu(
            callback, callback_data.season_id, int(data.get("hall_page") or 0), state
        )
        return
    if callback_data.action == hall_kb.HallOfFameDeleteAction.BACK_LIST:
        await _show_delete_menu(callback, callback_data.season_id, state)
        return
    current_state = await state.get_state()
    try:
        entry = await hall_of_fame_management_service.get_season_hall_of_fame(
            callback.from_user.id, callback_data.season_id
        )
    except HallOfFameSeasonNotFoundError:
        await callback.answer(text.HALL_OF_FAME_SEASON_NOT_FOUND, show_alert=True)
        return
    achievement = next(
        (item for item in entry.achievements if item.id == callback_data.achievement_id), None
    )
    if achievement is None:
        await callback.answer("Награда не найдена.", show_alert=True)
        return
    if callback_data.action == hall_kb.HallOfFameDeleteAction.OPEN:
        if current_state != HallOfFameStates.selecting_achievement_deletion:
            await callback.answer("Этот шаг устарел.", show_alert=True)
            return
        await state.set_state(HallOfFameStates.confirming_achievement_deletion)
        await callback.answer()
        if callback.message is not None:
            await edit_message_if_changed(
                callback.message,
                text=hall_fmt.delete_confirmation(achievement),
                reply_markup=hall_kb.delete_achievement_confirmation_keyboard(
                    season_id=entry.season_id,
                    achievement_id=achievement.id,
                ),
                parse_mode="Markdown",
            )
        return
    if current_state != HallOfFameStates.confirming_achievement_deletion:
        await callback.answer("Этот шаг устарел.", show_alert=True)
        return
    try:
        refreshed = await hall_of_fame_management_service.delete_achievement(
            callback.from_user.id,
            callback_data.season_id,
            callback_data.achievement_id,
        )
    except HallOfFameAchievementNotFoundError:
        await callback.answer("Награда не найдена.", show_alert=True)
        return
    await callback.answer("Награда удалена.")
    data = await state.get_data()
    page = int(data.get("hall_page") or 0)
    await state.clear()
    await state.update_data(hall_page=page)
    if callback.message is not None:
        await edit_message_if_changed(
            callback.message,
            text=hall_fmt.deleted_confirmation(achievement),
            reply_markup=None,
            parse_mode="Markdown",
        )
        await callback.message.answer(
            text=hall_fmt.achievements_menu(refreshed),
            reply_markup=hall_kb.achievements_keyboard(entry=refreshed, page=page),
            parse_mode="Markdown",
        )


@router.callback_query(hall_kb.HallOfFamePhotoCallback.filter())
async def select_hall_of_fame_photo_action(
    callback: CallbackQuery, callback_data: hall_kb.HallOfFamePhotoCallback, state: FSMContext
) -> None:
    if callback_data.action == hall_kb.HallOfFamePhotoAction.CANCEL:
        await _cancel(callback, state)
        return
    if callback_data.action == hall_kb.HallOfFamePhotoAction.BACK_CARD:
        data = await state.get_data()
        await _show_hall_card_callback(
            callback, callback_data.season_id, page=int(data.get("hall_page") or 0), state=state
        )
        return
    if callback_data.action == hall_kb.HallOfFamePhotoAction.BACK_MENU:
        await _show_photo_menu(callback, callback_data.season_id)
        return
    if callback_data.action == hall_kb.HallOfFamePhotoAction.OPEN_ADD:
        await _start_photo_flow(callback, callback_data.season_id, state)
        return
    if callback_data.action == hall_kb.HallOfFamePhotoAction.DELETE_ALL:
        await callback.answer()
        if callback.message is not None:
            await edit_message_if_changed(
                callback.message,
                text="Удалить все фотографии этого сезона?",
                reply_markup=hall_kb.photo_delete_confirmation_keyboard(
                    season_id=callback_data.season_id
                ),
            )
        return
    if callback_data.action == hall_kb.HallOfFamePhotoAction.CONFIRM_DELETE_ALL:
        await hall_of_fame_management_service.delete_all_photos(
            callback.from_user.id, callback_data.season_id
        )
        await callback.answer("Фотографии удалены.")
        await _show_photo_menu(callback, callback_data.season_id, answer_callback=False)
        return
    data = await state.get_data()
    try:
        await hall_of_fame_management_service.add_photo(
            callback.from_user.id,
            callback_data.season_id,
            telegram_file_id=str(data["hall_photo_file_id"]),
            telegram_file_unique_id=str(data["hall_photo_file_unique_id"]),
        )
    except KeyError:
        await callback.answer("Пришли фотографию.", show_alert=True)
        return
    await callback.answer("Фото сохранено.")
    await _show_photo_menu(callback, callback_data.season_id, answer_callback=False)


async def _show_achievements_menu(
    callback: CallbackQuery, season_id: int, page: int, state: FSMContext
) -> None:
    try:
        entry = await hall_of_fame_management_service.get_season_hall_of_fame(
            callback.from_user.id, season_id
        )
    except HallOfFameSeasonNotFoundError:
        await callback.answer(text.HALL_OF_FAME_SEASON_NOT_FOUND, show_alert=True)
        return
    await state.clear()
    await state.update_data(hall_page=page)
    await callback.answer()
    if callback.message is not None:
        await edit_message_if_changed(
            callback.message,
            text=hall_fmt.achievements_menu(entry),
            reply_markup=hall_kb.achievements_keyboard(entry=entry, page=page),
            parse_mode="Markdown",
        )


async def _show_delete_menu(callback: CallbackQuery, season_id: int, state: FSMContext) -> None:
    try:
        entry = await hall_of_fame_management_service.get_season_hall_of_fame(
            callback.from_user.id, season_id
        )
    except HallOfFameSeasonNotFoundError:
        await callback.answer(text.HALL_OF_FAME_SEASON_NOT_FOUND, show_alert=True)
        return
    if not entry.achievements:
        await callback.answer("В сезоне нет наград.", show_alert=True)
        return
    await state.set_state(HallOfFameStates.selecting_achievement_deletion)
    await callback.answer()
    if callback.message is not None:
        await edit_message_if_changed(
            callback.message,
            text=hall_fmt.delete_menu(entry),
            reply_markup=hall_kb.delete_achievements_keyboard(entry=entry),
            parse_mode="Markdown",
        )


async def _show_date_step(
    callback: CallbackQuery,
    season_id: int,
    field: hall_kb.HallOfFameField,
    state: FSMContext,
) -> None:
    entry = await hall_of_fame_management_service.get_season_hall_of_fame(
        callback.from_user.id, season_id
    )
    await state.set_state(HallOfFameStates.entering_awarded_at)
    await state.update_data(hall_season_id=season_id, hall_field=field.value)
    await callback.answer()
    if callback.message is not None:
        await edit_message_if_changed(
            callback.message,
            text=hall_fmt.date_prompt(entry, field),
            reply_markup=hall_kb.date_prompt_keyboard(
                season_id=season_id,
                field=field,
                today_label=club_clock.today().strftime("%d.%m.%Y"),
            ),
            parse_mode="Markdown",
        )
        await state.update_data(
            hall_date_prompt_chat_id=callback.message.chat.id,
            hall_date_prompt_message_id=callback.message.message_id,
        )


async def _show_player_name_step(
    callback: CallbackQuery,
    season_id: int,
    field: hall_kb.HallOfFameField,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    if not _wizard_state_matches(data, season_id, field):
        await callback.answer("Этот шаг устарел. Открой награду заново.", show_alert=True)
        return
    awarded_at = date.fromisoformat(str(data["hall_awarded_at"]))
    await callback.answer()
    if callback.message is not None:
        await _edit_player_name_step(
            callback.message,
            state,
            awarded_at,
            actor_telegram_id=callback.from_user.id,
        )


async def _show_photo_menu(
    callback: CallbackQuery, season_id: int, *, answer_callback: bool = True
) -> None:
    try:
        entry = await hall_of_fame_management_service.get_season_hall_of_fame(
            callback.from_user.id, season_id
        )
    except HallOfFameSeasonNotFoundError:
        await callback.answer(text.HALL_OF_FAME_SEASON_NOT_FOUND, show_alert=True)
        return
    if answer_callback:
        await callback.answer()
    if callback.message is not None:
        await edit_message_if_changed(
            callback.message,
            text=hall_fmt.photo_menu(entry),
            reply_markup=hall_kb.photo_menu_keyboard(season_id=season_id, page=0),
            parse_mode="Markdown",
        )


async def _start_photo_flow(callback: CallbackQuery, season_id: int, state: FSMContext) -> None:
    entry = await hall_of_fame_management_service.get_season_hall_of_fame(
        callback.from_user.id, season_id
    )
    await state.set_state(HallOfFameStates.collecting_photo)
    await state.update_data(hall_season_id=season_id, hall_season_name=entry.season_name)
    await callback.answer()
    if callback.message is not None:
        await edit_message_if_changed(
            callback.message,
            text=hall_fmt.photo_prompt(season_name=entry.season_name),
            reply_markup=hall_kb.photo_prompt_keyboard(season_id=season_id),
        )


@router.message(HallOfFameStates.collecting_photo, F.photo)
async def collect_hall_of_fame_photo(message: Message, state: FSMContext) -> None:
    if message.from_user is None or not message.photo:
        return
    data = await state.get_data()
    photo = message.photo[-1]
    await state.update_data(
        hall_photo_file_id=photo.file_id, hall_photo_file_unique_id=photo.file_unique_id
    )
    await message.answer_photo(photo.file_id)
    await message.answer(
        hall_fmt.photo_confirmation(season_name=str(data["hall_season_name"])),
        reply_markup=hall_kb.photo_confirmation_keyboard(season_id=int(data["hall_season_id"])),
    )


@router.message(HallOfFameStates.collecting_photo)
async def reject_hall_of_fame_non_photo(message: Message) -> None:
    await message.answer("Пришли фотографию.")


async def _show_season_list_callback(
    callback: CallbackQuery, page_number: int, state: FSMContext
) -> None:
    try:
        seasons = await hall_of_fame_management_service.list_seasons(callback.from_user.id)
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
    callback: CallbackQuery, season_id: int, *, page: int, state: FSMContext
) -> None:
    try:
        entry = await hall_of_fame_management_service.get_season_hall_of_fame(
            callback.from_user.id, season_id
        )
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


async def _show_candidate_list_from_state(
    callback: CallbackQuery, callback_data: hall_kb.HallOfFameConfirmCallback, state: FSMContext
) -> None:
    data = await state.get_data()
    candidates = await hall_of_fame_management_service.search_players(
        callback.from_user.id, str(data.get("hall_query") or "")
    )
    await state.set_state(HallOfFameStates.selecting_player)
    await callback.answer()
    if callback.message is not None:
        await edit_message_if_changed(
            callback.message,
            text=hall_fmt.search_results(candidates),
            reply_markup=hall_kb.search_results_keyboard(
                season_id=callback_data.season_id, field=callback_data.field, candidates=candidates
            ),
        )


async def _cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer(text.HALL_OF_FAME_CANCELLED)
    if callback.message is not None:
        await _delete_callback_message(callback)
        await send_superadmin_panel(
            callback.message,
            superadmin_telegram_id=callback.from_user.id,
            text=text.HALL_OF_FAME_CANCELLED,
        )


async def _clear_search_prompt_markup(message: Message, data: dict[str, object]) -> None:
    prompt_message_id = int(data.get("hall_prompt_message_id") or 0)
    if prompt_message_id <= 0:
        return
    try:
        await edit_message_reply_markup_by_id_if_changed(
            message.bot, chat_id=message.chat.id, message_id=prompt_message_id, reply_markup=None
        )
    except TelegramBadRequest:
        logger.info("Failed to clear Hall of Fame search prompt markup", exc_info=True)


async def _deactivate_message_from_state(
    message: Message,
    state: FSMContext,
    *,
    chat_key: str,
    message_key: str,
) -> None:
    data = await state.get_data()
    chat_id = int(data.get(chat_key) or message.chat.id)
    message_id = int(data.get(message_key) or 0)
    if message_id <= 0:
        return
    try:
        await edit_message_reply_markup_by_id_if_changed(
            message.bot,
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=None,
        )
    except TelegramBadRequest:
        logger.info("Failed to deactivate Hall of Fame wizard keyboard", exc_info=True)


def _wizard_state_matches(
    data: dict[str, object], season_id: int, field: hall_kb.HallOfFameField
) -> bool:
    return (
        int(data.get("hall_season_id") or 0) == season_id
        and str(data.get("hall_field") or "") == field.value
    )
