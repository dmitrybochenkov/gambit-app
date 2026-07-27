import re

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from app.bot.telegram import keyboards, texts
from app.bot.telegram.formatters import (
    format_profile,
    format_rating,
    format_tournament_label,
    format_tournament_schedule,
)
from app.bot.telegram.notifications import notify_admins_about_registration
from app.bot.telegram.states import RegistrationStates
from app.services.pagination import pagination_service
from app.services.profile_service import ProfileNotAllowedError, profile_service
from app.services.rating_service import RatingNotAllowedError, rating_service
from app.services.tournament_service import (
    TournamentCancellationUnavailableError,
    TournamentRegistrationNotAllowedError,
    TournamentScheduleNotAllowedError,
    TournamentUnavailableError,
    tournament_service,
)
from app.services.user_service import (
    IdentityAlreadyExistsError,
    InvalidDisplayNameError,
    RegistrationCandidateNotFoundError,
    RegistrationNotAllowedError,
    user_service,
)

router = Router(name="user")


def _clean_text(value: str) -> str:
    return " ".join(value.split())


def _is_valid_display_name(value: str) -> bool:
    return 1 <= len(value) <= 255 and re.fullmatch(r"[\w\s.@-]+", value) is not None


async def _send_registration_intro(message: Message, state: FSMContext) -> None:
    await message.answer(
        texts.user.REGISTRATION_GREETING,
        reply_markup=keyboards.registration_start_keyboard(),
    )
    await state.set_state(None)


async def _delete_message(message: Message) -> None:
    try:
        await message.delete()
    except TelegramBadRequest:
        pass


async def _delete_prompt_and_input(message: Message, state: FSMContext) -> None:
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

    await _delete_message(message)
    await state.update_data(prompt_message_id=None)


async def _send_input_prompt(
    message: Message,
    state: FSMContext,
    text: str,
) -> None:
    prompt = await message.answer(text)
    await state.update_data(prompt_message_id=prompt.message_id)


@router.message(CommandStart())
async def start_command(message: Message, state: FSMContext) -> None:
    await state.clear()
    if message.from_user is None:
        return

    user = await user_service.get_by_telegram_id(message.from_user.id)
    if user is None:
        if await user_service.get_pending_registration_by_telegram_id(message.from_user.id):
            await message.answer(
                texts.user.REGISTRATION_PENDING,
                reply_markup=ReplyKeyboardRemove(),
            )
            return
        await _send_registration_intro(message, state)
        return

    if user.is_blocked:
        await message.answer(
            texts.user.BOT_ACCESS_BLOCKED,
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    await message.answer(
        texts.user.welcome_back(user.display_name),
        reply_markup=keyboards.main_keyboard_for_player(user),
    )


@router.message(F.text == keyboards.MAIN_SCHEDULE)
async def show_tournament_schedule(message: Message) -> None:
    if message.from_user is None:
        return

    try:
        tournaments = await tournament_service.get_schedule_for_player(message.from_user.id)
    except TournamentScheduleNotAllowedError:
        await message.answer(texts.user.SCHEDULE_UNAVAILABLE)
        return

    await message.answer(format_tournament_schedule(tournaments))


@router.message(F.text == keyboards.MAIN_ADDRESS)
async def show_club_address(message: Message) -> None:
    if message.from_user is None:
        return

    player = await user_service.get_by_telegram_id(message.from_user.id)
    if player is None or not player.is_active:
        await message.answer(texts.user.ADDRESS_UNAVAILABLE)
        return

    await message.answer(texts.user.CLUB_ADDRESS)


@router.message(F.text == keyboards.MAIN_RATING)
async def show_rating_menu(message: Message) -> None:
    if message.from_user is None:
        return

    player = await user_service.get_by_telegram_id(message.from_user.id)
    if player is None or not player.is_active:
        await message.answer(texts.user.RATING_UNAVAILABLE)
        return

    await message.answer(
        texts.user.RATING_MENU_PROMPT,
        reply_markup=keyboards.rating_keyboard(),
    )


@router.callback_query(keyboards.RatingCallback.filter())
async def show_rating(
    callback: CallbackQuery,
    callback_data: keyboards.RatingCallback,
) -> None:
    try:
        rating = await rating_service.get_rating_for_player(
            telegram_id=callback.from_user.id,
            kind=callback_data.kind,
        )
    except RatingNotAllowedError:
        await callback.answer(
            texts.user.RATING_ACTIVE_ONLY,
            show_alert=True,
        )
        return

    page_number = rating_page_for_player(
        rating.rows,
        current_player_id=rating.current_player_id,
        requested_page=callback_data.page,
    )
    page = pagination_service.paginate(
        rating.rows,
        page=page_number,
        page_size=keyboards.RATING_PAGE_SIZE,
    )
    await callback.answer()
    if callback.message is not None:
        try:
            await callback.message.edit_text(
                format_rating(rating.title, page, rating.current_player_id),
                reply_markup=keyboards.rating_page_keyboard(callback_data.kind, page),
                parse_mode="Markdown",
            )
        except TelegramBadRequest:
            pass


def rating_page_for_player(
    rows: list[object],
    *,
    current_player_id: int,
    requested_page: int,
) -> int:
    if requested_page >= 0:
        return requested_page
    for index, row in enumerate(rows):
        if getattr(row, "player_id", None) == current_player_id:
            return index // keyboards.RATING_PAGE_SIZE
    return 0


@router.callback_query(keyboards.RatingCancelCallback.filter())
async def cancel_rating(
    callback: CallbackQuery,
    callback_data: keyboards.RatingCancelCallback,
) -> None:
    answer = (
        "Рейтинг закрыт" if callback_data.action == keyboards.RatingCancelAction.CLOSE else "Отмена"
    )
    await callback.answer(answer)
    if callback.message is None:
        return

    await _delete_message(callback.message)
    await callback.message.answer(answer)


@router.message(F.text == keyboards.MAIN_PROFILE)
async def show_profile_menu(message: Message) -> None:
    if message.from_user is None:
        return

    player = await user_service.get_by_telegram_id(message.from_user.id)
    if player is None or not player.is_active:
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


@router.message(F.text == keyboards.MAIN_REGISTER)
async def show_tournaments_for_registration(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return

    try:
        tournaments = await tournament_service.get_registration_options_for_player(
            message.from_user.id
        )
    except TournamentRegistrationNotAllowedError:
        await message.answer(texts.user.TOURNAMENT_REGISTRATION_UNAVAILABLE)
        return

    if not tournaments:
        await message.answer(texts.user.TOURNAMENT_REGISTRATION_EMPTY)
        return

    registered_tournaments = await tournament_service.get_player_upcoming_registrations(
        message.from_user.id
    )
    registered_tournament_ids = {tournament.id for tournament in registered_tournaments}
    selected_tournament_ids = [
        tournament.id for tournament in tournaments if tournament.id in registered_tournament_ids
    ]
    await state.update_data(tournament_registration_selection=selected_tournament_ids)
    page = pagination_service.paginate(
        tournaments,
        page=0,
        page_size=keyboards.TOURNAMENT_LIST_PAGE_SIZE,
    )
    await message.answer(
        texts.user.TOURNAMENT_REGISTRATION_PROMPT,
        reply_markup=keyboards.tournament_registration_keyboard(
            page,
            set(selected_tournament_ids),
        ),
    )


@router.callback_query(keyboards.TournamentRegistrationCallback.filter())
async def register_for_tournament(
    callback: CallbackQuery,
    callback_data: keyboards.TournamentRegistrationCallback,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    selected_tournament_ids = set(data.get("tournament_registration_selection", []))
    if callback_data.action == keyboards.TournamentListAction.PAGE:
        answer = None
    elif callback_data.tournament_id in selected_tournament_ids:
        selected_tournament_ids.remove(callback_data.tournament_id)
        answer = texts.user.TOURNAMENT_REMOVED_FROM_SELECTION
    else:
        selected_tournament_ids.add(callback_data.tournament_id)
        answer = texts.user.TOURNAMENT_ADDED_TO_SELECTION

    try:
        tournaments = await tournament_service.get_registration_options_for_player(
            callback.from_user.id
        )
    except TournamentRegistrationNotAllowedError:
        await callback.answer(
            texts.user.TOURNAMENT_REGISTRATION_ACTIVE_ONLY,
            show_alert=True,
        )
        return
    available_ids = {tournament.id for tournament in tournaments}
    selected_tournament_ids &= available_ids
    await state.update_data(tournament_registration_selection=sorted(selected_tournament_ids))
    page = pagination_service.paginate(
        tournaments,
        page=callback_data.page,
        page_size=keyboards.TOURNAMENT_LIST_PAGE_SIZE,
    )

    if callback.message is not None:
        await callback.message.edit_reply_markup(
            reply_markup=keyboards.tournament_registration_keyboard(
                page,
                selected_tournament_ids,
            )
        )
    if answer is None:
        await callback.answer()
    else:
        await callback.answer(answer)


@router.callback_query(F.data == keyboards.CONFIRM_TOURNAMENT_REGISTRATION_CALLBACK)
async def confirm_tournament_registration(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    tournament_ids = data.get("tournament_registration_selection", [])
    if not tournament_ids:
        await callback.answer(texts.user.TOURNAMENT_SELECTION_EMPTY, show_alert=True)
        return

    try:
        tournaments = await tournament_service.register_player_for_tournaments(
            telegram_id=callback.from_user.id,
            tournament_ids=tournament_ids,
        )
    except TournamentRegistrationNotAllowedError:
        await callback.answer(
            texts.user.TOURNAMENT_REGISTRATION_ACTIVE_ONLY,
            show_alert=True,
        )
        return
    except TournamentUnavailableError:
        await callback.answer(texts.user.TOURNAMENT_UNAVAILABLE, show_alert=True)
        return
    await state.update_data(tournament_registration_selection=[])
    await callback.answer(texts.user.ACTION_DONE)
    if callback.message is not None:
        await _delete_message(callback.message)
        await callback.message.answer(
            texts.user.tournament_registration_success(
                [format_tournament_label(tournament) for tournament in tournaments]
            )
        )


@router.callback_query(F.data == keyboards.CANCEL_TOURNAMENT_REGISTRATION_CALLBACK)
async def cancel_tournament_registration_selection(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    await state.update_data(tournament_registration_selection=[])
    await callback.answer(texts.user.TOURNAMENT_REGISTRATION_CANCELLED)
    if callback.message is not None:
        await _delete_message(callback.message)
        await callback.message.answer(texts.user.TOURNAMENT_REGISTRATION_CANCELLED)


@router.message(F.text == keyboards.MAIN_CANCEL_REGISTRATION)
async def show_tournaments_for_cancellation(
    message: Message,
    state: FSMContext,
) -> None:
    if message.from_user is None:
        return

    try:
        tournaments = await tournament_service.get_player_upcoming_registrations(
            message.from_user.id
        )
    except TournamentRegistrationNotAllowedError:
        await message.answer(texts.user.TOURNAMENT_CANCELLATION_UNAVAILABLE)
        return

    if not tournaments:
        await message.answer(texts.user.TOURNAMENT_CANCELLATION_EMPTY)
        return

    await state.update_data(tournament_cancellation_selection=[])
    page = pagination_service.paginate(
        tournaments,
        page=0,
        page_size=keyboards.TOURNAMENT_LIST_PAGE_SIZE,
    )
    await message.answer(
        texts.user.TOURNAMENT_CANCELLATION_PROMPT,
        reply_markup=keyboards.tournament_cancellation_keyboard(page),
    )


@router.callback_query(keyboards.TournamentCancellationCallback.filter())
async def select_tournament_for_cancellation(
    callback: CallbackQuery,
    callback_data: keyboards.TournamentCancellationCallback,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    selected_tournament_ids = set(data.get("tournament_cancellation_selection", []))
    if callback_data.action == keyboards.TournamentListAction.PAGE:
        answer = None
    elif callback_data.tournament_id in selected_tournament_ids:
        selected_tournament_ids.remove(callback_data.tournament_id)
        answer = texts.user.TOURNAMENT_REMOVED_FROM_SELECTION
    else:
        selected_tournament_ids.add(callback_data.tournament_id)
        answer = texts.user.TOURNAMENT_ADDED_TO_SELECTION

    try:
        tournaments = await tournament_service.get_player_upcoming_registrations(
            callback.from_user.id
        )
    except TournamentRegistrationNotAllowedError:
        await callback.answer(
            texts.user.TOURNAMENT_CANCELLATION_ACTIVE_ONLY,
            show_alert=True,
        )
        return

    available_ids = {tournament.id for tournament in tournaments}
    selected_tournament_ids &= available_ids
    await state.update_data(tournament_cancellation_selection=sorted(selected_tournament_ids))
    page = pagination_service.paginate(
        tournaments,
        page=callback_data.page,
        page_size=keyboards.TOURNAMENT_LIST_PAGE_SIZE,
    )
    if callback.message is not None:
        await callback.message.edit_reply_markup(
            reply_markup=keyboards.tournament_cancellation_keyboard(
                page,
                selected_tournament_ids,
            )
        )
    if answer is None:
        await callback.answer()
    else:
        await callback.answer(answer)


@router.callback_query(F.data == keyboards.CONFIRM_TOURNAMENT_CANCELLATION_CALLBACK)
async def confirm_tournament_cancellation(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    tournament_ids = data.get("tournament_cancellation_selection", [])
    if not tournament_ids:
        await callback.answer(texts.user.TOURNAMENT_SELECTION_EMPTY, show_alert=True)
        return

    try:
        tournaments = await tournament_service.cancel_player_tournament_registrations(
            telegram_id=callback.from_user.id,
            tournament_ids=tournament_ids,
        )
    except TournamentRegistrationNotAllowedError:
        await callback.answer(
            texts.user.TOURNAMENT_CANCELLATION_ACTIVE_ONLY,
            show_alert=True,
        )
        return
    except TournamentCancellationUnavailableError:
        await callback.answer(
            texts.user.TOURNAMENT_CANCELLATION_UNAVAILABLE_ITEM,
            show_alert=True,
        )
        return

    await state.update_data(tournament_cancellation_selection=[])
    await callback.answer(texts.user.ACTION_DONE)
    if callback.message is not None:
        await _delete_message(callback.message)
        await callback.message.answer(
            texts.user.tournament_cancellation_success(
                [format_tournament_label(tournament) for tournament in tournaments]
            )
        )


@router.callback_query(F.data == keyboards.CANCEL_TOURNAMENT_CANCELLATION_CALLBACK)
async def cancel_tournament_cancellation_selection(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    await state.update_data(tournament_cancellation_selection=[])
    await callback.answer(texts.user.TOURNAMENT_CANCELLATION_CANCELLED)
    if callback.message is not None:
        await _delete_message(callback.message)
        await callback.message.answer(texts.user.TOURNAMENT_CANCELLATION_CANCELLED)


@router.callback_query(F.data == keyboards.REGISTRATION_NEW_PLAYER_CALLBACK)
async def choose_new_player_registration(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is None:
        return

    await _delete_message(callback.message)
    await state.set_state(RegistrationStates.entering_new_display_name)
    await _send_input_prompt(callback.message, state, texts.user.REGISTRATION_NEW_PLAYER_PROMPT)


@router.callback_query(F.data == keyboards.REGISTRATION_LINK_EXISTING_CALLBACK)
async def choose_link_existing_registration(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is None:
        return

    await _delete_message(callback.message)
    await state.set_state(RegistrationStates.entering_link_name)
    await _send_input_prompt(callback.message, state, texts.user.REGISTRATION_LINK_NAME_PROMPT)


@router.callback_query(F.data == keyboards.REGISTRATION_RETRY_LINK_CALLBACK)
async def retry_link_existing_registration(callback: CallbackQuery, state: FSMContext) -> None:
    await choose_link_existing_registration(callback, state)


@router.callback_query(F.data == keyboards.REGISTRATION_BACK_CALLBACK)
async def back_to_registration_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is None:
        return

    await _delete_message(callback.message)
    await state.clear()
    await _send_registration_intro(callback.message, state)


@router.message(RegistrationStates.entering_new_display_name)
async def enter_new_display_name(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return

    display_name = _clean_text(message.text or "")
    if not _is_valid_display_name(display_name):
        await message.answer(texts.user.INVALID_DISPLAY_NAME)
        return

    try:
        request = await user_service.submit_new_player_registration(
            message.from_user.id,
            display_name,
        )
    except IdentityAlreadyExistsError:
        await _delete_prompt_and_input(message, state)
        await state.clear()
        await message.answer(
            texts.user.DISPLAY_NAME_ALREADY_EXISTS,
            reply_markup=keyboards.registration_start_keyboard(),
        )
        return
    except (InvalidDisplayNameError, RegistrationNotAllowedError):
        await message.answer(texts.user.REGISTRATION_NOT_ALLOWED)
        return

    await _delete_prompt_and_input(message, state)
    await state.clear()
    await notify_admins_about_registration(message.bot, request.id)
    await message.answer(texts.user.REGISTRATION_SUBMITTED)


@router.message(RegistrationStates.entering_link_name)
async def enter_link_name(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return

    requested_link_name = _clean_text(message.text or "")
    if not _is_valid_display_name(requested_link_name):
        await message.answer(texts.user.INVALID_DISPLAY_NAME)
        return

    try:
        request = await user_service.submit_link_existing_registration(
            message.from_user.id,
            requested_link_name,
        )
    except RegistrationCandidateNotFoundError:
        await _delete_prompt_and_input(message, state)
        await state.clear()
        await message.answer(
            texts.user.REGISTRATION_LINK_NOT_FOUND,
            reply_markup=keyboards.registration_link_not_found_keyboard(),
        )
        return
    except (InvalidDisplayNameError, RegistrationNotAllowedError):
        await message.answer(texts.user.REGISTRATION_NOT_ALLOWED)
        return

    await _delete_prompt_and_input(message, state)
    await state.clear()
    await notify_admins_about_registration(message.bot, request.id)
    await message.answer(texts.user.REGISTRATION_SUBMITTED)
