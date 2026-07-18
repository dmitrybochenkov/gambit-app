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
from app.bot.telegram.states import RegistrationMode, RegistrationStates
from app.services.pagination import pagination_service
from app.services.player_service import (
    IdentityAlreadyExistsError,
    RegistrationNotAllowedError,
    player_service,
)
from app.services.profile_service import ProfileNotAllowedError, profile_service
from app.services.rating_service import RatingNotAllowedError, rating_service
from app.services.tournament_service import (
    TournamentCancellationUnavailableError,
    TournamentFullError,
    TournamentRegistrationNotAllowedError,
    TournamentScheduleNotAllowedError,
    TournamentUnavailableError,
    tournament_service,
)

router = Router(name="user")


def _clean_text(value: str) -> str:
    return " ".join(value.split())


def _is_valid_full_name(value: str) -> bool:
    return 3 <= len(value) <= 255 and len(value.split()) >= 2


def _is_valid_nickname(value: str) -> bool:
    return 2 <= len(value) <= 100


async def _send_registration_intro(message: Message) -> None:
    await message.answer(
        texts.user.REGISTRATION_GREETING,
        reply_markup=ReplyKeyboardRemove(),
    )
    await message.answer(
        texts.user.REGISTRATION_MODE_PROMPT,
        reply_markup=keyboards.registration_mode_keyboard(),
    )


async def _send_confirmation(message: Message, state: FSMContext) -> None:
    data = await state.get_data()

    await state.set_state(RegistrationStates.confirming)
    await message.answer(
        texts.user.registration_confirmation(
            full_name=data.get("full_name"),
            nickname=data.get("nickname"),
        ),
        reply_markup=keyboards.registration_confirmation_keyboard(),
    )


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

    player = await player_service.get_by_telegram_id(message.from_user.id)
    if player is None:
        await _send_registration_intro(message)
        return

    if player.is_pending:
        await message.answer(
            texts.user.REGISTRATION_PENDING,
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    if player.is_blocked:
        await message.answer(
            texts.user.BOT_ACCESS_BLOCKED,
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    await message.answer(
        texts.user.welcome_back(player.display_name),
        reply_markup=keyboards.main_keyboard_for_player(player),
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

    player = await player_service.get_by_telegram_id(message.from_user.id)
    if player is None or not player.is_active:
        await message.answer(texts.user.ADDRESS_UNAVAILABLE)
        return

    await message.answer(texts.user.CLUB_ADDRESS)


@router.message(F.text == keyboards.MAIN_RATING)
async def show_rating_menu(message: Message) -> None:
    if message.from_user is None:
        return

    player = await player_service.get_by_telegram_id(message.from_user.id)
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

    page = pagination_service.paginate(
        rating.rows,
        page=callback_data.page,
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


@router.callback_query(keyboards.RatingCancelCallback.filter())
async def cancel_rating(
    callback: CallbackQuery,
    callback_data: keyboards.RatingCancelCallback,
) -> None:
    answer = (
        "Рейтинг закрыт"
        if callback_data.action == keyboards.RatingCancelAction.CLOSE
        else "Отмена"
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

    player = await player_service.get_by_telegram_id(message.from_user.id)
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

    await state.update_data(tournament_registration_selection=[])
    await message.answer(
        texts.user.TOURNAMENT_REGISTRATION_PROMPT,
        reply_markup=keyboards.tournament_registration_keyboard(tournaments),
    )


@router.callback_query(keyboards.TournamentRegistrationCallback.filter())
async def register_for_tournament(
    callback: CallbackQuery,
    callback_data: keyboards.TournamentRegistrationCallback,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    selected_tournament_ids = set(data.get("tournament_registration_selection", []))
    if callback_data.tournament_id in selected_tournament_ids:
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
    await state.update_data(
        tournament_registration_selection=sorted(selected_tournament_ids)
    )

    if callback.message is not None:
        await callback.message.edit_reply_markup(
            reply_markup=keyboards.tournament_registration_keyboard(
                tournaments,
                selected_tournament_ids,
            )
        )
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
    except TournamentFullError:
        await callback.answer(texts.user.TOURNAMENT_FULL, show_alert=True)
        return

    await state.update_data(tournament_registration_selection=[])
    await callback.answer(texts.user.ACTION_DONE)
    if callback.message is not None:
        await callback.message.edit_reply_markup(reply_markup=None)
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
    await callback.answer()
    if callback.message is not None:
        await callback.message.edit_reply_markup(reply_markup=None)
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
    await message.answer(
        texts.user.TOURNAMENT_CANCELLATION_PROMPT,
        reply_markup=keyboards.tournament_cancellation_keyboard(tournaments),
    )


@router.callback_query(keyboards.TournamentCancellationCallback.filter())
async def select_tournament_for_cancellation(
    callback: CallbackQuery,
    callback_data: keyboards.TournamentCancellationCallback,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    selected_tournament_ids = set(data.get("tournament_cancellation_selection", []))
    if callback_data.tournament_id in selected_tournament_ids:
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
    await state.update_data(
        tournament_cancellation_selection=sorted(selected_tournament_ids)
    )
    if callback.message is not None:
        await callback.message.edit_reply_markup(
            reply_markup=keyboards.tournament_cancellation_keyboard(
                tournaments,
                selected_tournament_ids,
            )
        )
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
        await callback.message.edit_reply_markup(reply_markup=None)
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
    await callback.answer()
    if callback.message is not None:
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(texts.user.TOURNAMENT_CANCELLATION_CANCELLED)


@router.callback_query(keyboards.RegistrationModeCallback.filter())
async def choose_registration_mode(
    callback: CallbackQuery,
    callback_data: keyboards.RegistrationModeCallback,
    state: FSMContext,
) -> None:
    await callback.answer()
    if callback.message is None:
        return

    await state.clear()
    await state.update_data(mode=callback_data.mode.value)
    await _delete_message(callback.message)

    if callback_data.mode == RegistrationMode.NICKNAME:
        await state.set_state(RegistrationStates.entering_nickname)
        await _send_input_prompt(callback.message, state, texts.user.ENTER_NICKNAME)
        return

    await state.set_state(RegistrationStates.entering_full_name)
    await _send_input_prompt(callback.message, state, texts.user.ENTER_FULL_NAME)


@router.message(RegistrationStates.entering_full_name)
async def enter_full_name(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return

    full_name = _clean_text(message.text or "")
    if not _is_valid_full_name(full_name):
        await message.answer(texts.user.INVALID_FULL_NAME)
        return

    try:
        await player_service.validate_unique_identity(
            telegram_id=message.from_user.id,
            full_name=full_name,
            nickname=None,
        )
    except IdentityAlreadyExistsError:
        await message.answer(texts.user.FULL_NAME_ALREADY_EXISTS)
        return

    await _delete_prompt_and_input(message, state)
    await state.update_data(full_name=full_name)
    data = await state.get_data()
    if data["mode"] == RegistrationMode.BOTH.value:
        await state.set_state(RegistrationStates.entering_nickname)
        await _send_input_prompt(
            message,
            state,
            texts.user.ENTER_NICKNAME_AFTER_FULL_NAME,
        )
        return

    await _send_confirmation(message, state)


@router.message(RegistrationStates.entering_nickname)
async def enter_nickname(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return

    nickname = _clean_text(message.text or "")
    if not _is_valid_nickname(nickname):
        await message.answer(texts.user.INVALID_NICKNAME)
        return

    try:
        await player_service.validate_unique_identity(
            telegram_id=message.from_user.id,
            full_name=None,
            nickname=nickname,
        )
    except IdentityAlreadyExistsError:
        await message.answer(texts.user.NICKNAME_ALREADY_EXISTS)
        return

    await _delete_prompt_and_input(message, state)
    await state.update_data(nickname=nickname)
    await _send_confirmation(message, state)


@router.callback_query(F.data == keyboards.RESTART_REGISTRATION_CALLBACK)
async def restart_registration(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is None:
        return

    await _delete_message(callback.message)
    await state.clear()
    await _send_registration_intro(callback.message)


@router.callback_query(F.data == keyboards.CONFIRM_REGISTRATION_CALLBACK)
async def confirm_registration(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is None:
        return

    await _delete_message(callback.message)
    data = await state.get_data()
    full_name = data.get("full_name")
    nickname = data.get("nickname")
    if not full_name and not nickname:
        await state.clear()
        await callback.message.answer(texts.user.REGISTRATION_EXPIRED)
        return

    try:
        player = await player_service.submit_registration(
            telegram_id=callback.from_user.id,
            full_name=full_name,
            nickname=nickname,
        )
    except IdentityAlreadyExistsError as error:
        target_state = (
            RegistrationStates.entering_full_name
            if error.field == "full_name"
            else RegistrationStates.entering_nickname
        )
        await state.set_state(target_state)
        await _send_input_prompt(
            callback.message,
            state,
            texts.user.REGISTRATION_DATA_ALREADY_EXISTS,
        )
        return
    except RegistrationNotAllowedError:
        await state.clear()
        await callback.message.answer(texts.user.REGISTRATION_NOT_ALLOWED)
        return

    await state.clear()
    await notify_admins_about_registration(callback.bot, player)
    await callback.message.answer(texts.user.registration_submitted(player.display_name))
