from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from app.bot.telegram.formatters import format_tournament_label, format_tournament_schedule
from app.bot.telegram.keyboards.main import main_keyboard
from app.bot.telegram.keyboards.registration import (
    CONFIRM_REGISTRATION_CALLBACK,
    RESTART_REGISTRATION_CALLBACK,
    RegistrationModeCallback,
    registration_confirmation_keyboard,
    registration_mode_keyboard,
)
from app.bot.telegram.keyboards.tournaments import (
    CANCEL_TOURNAMENT_REGISTRATION_CALLBACK,
    CONFIRM_TOURNAMENT_REGISTRATION_CALLBACK,
    TournamentRegistrationCallback,
    tournament_registration_keyboard,
)
from app.bot.telegram.notifications import notify_admins_about_registration
from app.bot.telegram.states import RegistrationMode, RegistrationStates
from app.db.models.enums import PlayerRole, PlayerStatus
from app.services.player_service import (
    IdentityAlreadyExistsError,
    RegistrationNotAllowedError,
    player_service,
)
from app.services.tournament_service import (
    TournamentFullError,
    TournamentRegistrationNotAllowedError,
    TournamentUnavailableError,
    tournament_service,
)

router = Router(name="user")

REGISTRATION_GREETING = (
    "🤚 Добро пожаловать в покерный клуб Гамбит. Я бот, который поможет тебе "
    "стать участником нашего комьюнити.\n\n"
    "Чтобы я знал, как к тебе обращаться, и мог отслеживать твои достижения, "
    "введи свои фамилию и имя и/или никнейм.\n\n"
    "❌ Запрещено использовать ненормативную лексику!\n\n"
    "✅ Чтобы корректно учесть твои достижения, вводи никнейм, под которым "
    "ты играл в клубе ранее."
)


def _clean_text(value: str) -> str:
    return " ".join(value.split())


def _is_valid_full_name(value: str) -> bool:
    return 3 <= len(value) <= 255 and len(value.split()) >= 2


def _is_valid_nickname(value: str) -> bool:
    return 2 <= len(value) <= 100


async def _send_registration_intro(message: Message) -> None:
    await message.answer(REGISTRATION_GREETING, reply_markup=ReplyKeyboardRemove())
    await message.answer(
        "Выбери вариант регистрации:",
        reply_markup=registration_mode_keyboard(),
    )


async def _send_confirmation(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    lines = ["Проверь введенные данные:"]
    if full_name := data.get("full_name"):
        lines.append(f"Фамилия и имя: {full_name}")
    if nickname := data.get("nickname"):
        lines.append(f"Никнейм: {nickname}")

    await state.set_state(RegistrationStates.confirming)
    await message.answer(
        "\n".join(lines),
        reply_markup=registration_confirmation_keyboard(),
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
    if player is None or player.status == PlayerStatus.REJECTED:
        await _send_registration_intro(message)
        return

    if player.status == PlayerStatus.PENDING:
        await message.answer(
            "Твоя заявка на регистрацию находится на проверке.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    if player.status == PlayerStatus.BLOCKED:
        await message.answer(
            "Доступ к боту заблокирован.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    await message.answer(
        f"{player.display_name}, добро пожаловать!",
        reply_markup=main_keyboard(
            is_admin=player.role in {PlayerRole.ADMIN, PlayerRole.SUPERADMIN}
        ),
    )


@router.message(F.text == "Расписание турниров")
async def show_tournament_schedule(message: Message) -> None:
    if message.from_user is None:
        return

    player = await player_service.get_by_telegram_id(message.from_user.id)
    if player is None or player.status != PlayerStatus.ACTIVE:
        await message.answer("Расписание доступно зарегистрированным игрокам. Нажми /start.")
        return

    tournaments = await tournament_service.get_upcoming_schedule()
    await message.answer(format_tournament_schedule(tournaments))


@router.message(F.text == "Как нас найти")
async def show_club_address(message: Message) -> None:
    if message.from_user is None:
        return

    player = await player_service.get_by_telegram_id(message.from_user.id)
    if player is None or player.status != PlayerStatus.ACTIVE:
        await message.answer("Адрес доступен зарегистрированным игрокам. Нажми /start.")
        return

    await message.answer("Адрес: г. Орехово-Зуево, д. 1")


@router.message(F.text == "Записаться")
async def show_tournaments_for_registration(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return

    player = await player_service.get_by_telegram_id(message.from_user.id)
    if player is None or player.status != PlayerStatus.ACTIVE:
        await message.answer("Запись доступна зарегистрированным игрокам. Нажми /start.")
        return

    tournaments = await tournament_service.get_upcoming_schedule()
    if not tournaments:
        await message.answer("Ближайших турниров для записи пока нет.")
        return

    await state.update_data(tournament_registration_selection=[])
    await message.answer(
        "Выбери даты турниров, на которые хочешь записаться, и нажми «Подтвердить».",
        reply_markup=tournament_registration_keyboard(tournaments),
    )


@router.callback_query(TournamentRegistrationCallback.filter())
async def register_for_tournament(
    callback: CallbackQuery,
    callback_data: TournamentRegistrationCallback,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    selected_tournament_ids = set(data.get("tournament_registration_selection", []))
    if callback_data.tournament_id in selected_tournament_ids:
        selected_tournament_ids.remove(callback_data.tournament_id)
        answer = "Турнир убран из выбранных."
    else:
        selected_tournament_ids.add(callback_data.tournament_id)
        answer = "Турнир добавлен."

    tournaments = await tournament_service.get_upcoming_schedule()
    available_ids = {tournament.id for tournament in tournaments}
    selected_tournament_ids &= available_ids
    await state.update_data(
        tournament_registration_selection=sorted(selected_tournament_ids)
    )

    if callback.message is not None:
        await callback.message.edit_reply_markup(
            reply_markup=tournament_registration_keyboard(
                tournaments,
                selected_tournament_ids,
            )
        )
    await callback.answer(answer)


@router.callback_query(F.data == CONFIRM_TOURNAMENT_REGISTRATION_CALLBACK)
async def confirm_tournament_registration(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    tournament_ids = data.get("tournament_registration_selection", [])
    if not tournament_ids:
        await callback.answer("Сначала выбери хотя бы один турнир.", show_alert=True)
        return

    try:
        tournaments = await tournament_service.register_player_for_tournaments(
            telegram_id=callback.from_user.id,
            tournament_ids=tournament_ids,
        )
    except TournamentRegistrationNotAllowedError:
        await callback.answer("Запись доступна только активным игрокам.", show_alert=True)
        return
    except TournamentUnavailableError:
        await callback.answer("Этот турнир уже недоступен для записи.", show_alert=True)
        return
    except TournamentFullError:
        await callback.answer("К сожалению, свободных мест уже нет.", show_alert=True)
        return

    await state.update_data(tournament_registration_selection=[])
    await callback.answer("Готово!")
    if callback.message is not None:
        await callback.message.edit_reply_markup(reply_markup=None)
        heading = (
            "Вы записались на турнир:"
            if len(tournaments) == 1
            else "Вы записались на турниры:"
        )
        tournament_lines = "\n".join(
            f"• {format_tournament_label(tournament)}"
            for tournament in tournaments
        )
        await callback.message.answer(
            f"{heading}\n\n{tournament_lines}\n\n"
            "Будем благодарны, если при изменении планов, "
            "вы отмените запись заранее."
        )


@router.callback_query(F.data == CANCEL_TOURNAMENT_REGISTRATION_CALLBACK)
async def cancel_tournament_registration_selection(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    await state.update_data(tournament_registration_selection=[])
    await callback.answer()
    if callback.message is not None:
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer("Запись на турнир(ы) отменена.")


@router.callback_query(RegistrationModeCallback.filter())
async def choose_registration_mode(
    callback: CallbackQuery,
    callback_data: RegistrationModeCallback,
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
        await _send_input_prompt(callback.message, state, "Введи никнейм.")
        return

    await state.set_state(RegistrationStates.entering_full_name)
    await _send_input_prompt(callback.message, state, "Введи фамилию и имя.")


@router.message(RegistrationStates.entering_full_name)
async def enter_full_name(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return

    full_name = _clean_text(message.text or "")
    if not _is_valid_full_name(full_name):
        await message.answer("Введи фамилию и имя через пробел.")
        return

    try:
        await player_service.validate_unique_identity(
            telegram_id=message.from_user.id,
            full_name=full_name,
            nickname=None,
        )
    except IdentityAlreadyExistsError:
        await message.answer("Такие имя и фамилия уже существуют. Попробуй другие.")
        return

    await _delete_prompt_and_input(message, state)
    await state.update_data(full_name=full_name)
    data = await state.get_data()
    if data["mode"] == RegistrationMode.BOTH.value:
        await state.set_state(RegistrationStates.entering_nickname)
        await _send_input_prompt(message, state, "Теперь введи никнейм.")
        return

    await _send_confirmation(message, state)


@router.message(RegistrationStates.entering_nickname)
async def enter_nickname(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return

    nickname = _clean_text(message.text or "")
    if not _is_valid_nickname(nickname):
        await message.answer("Никнейм должен содержать от 2 до 100 символов.")
        return

    try:
        await player_service.validate_unique_identity(
            telegram_id=message.from_user.id,
            full_name=None,
            nickname=nickname,
        )
    except IdentityAlreadyExistsError:
        await message.answer("Такой никнейм уже существует. Попробуй другой.")
        return

    await _delete_prompt_and_input(message, state)
    await state.update_data(nickname=nickname)
    await _send_confirmation(message, state)


@router.callback_query(F.data == RESTART_REGISTRATION_CALLBACK)
async def restart_registration(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is None:
        return

    await _delete_message(callback.message)
    await state.clear()
    await _send_registration_intro(callback.message)


@router.callback_query(F.data == CONFIRM_REGISTRATION_CALLBACK)
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
        await callback.message.answer("Данные регистрации устарели. Начни заново: /start")
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
            "Эти данные уже заняты. Введи другое значение.",
        )
        return
    except RegistrationNotAllowedError:
        await state.clear()
        await callback.message.answer("Повторная регистрация недоступна.")
        return

    await state.clear()
    await notify_admins_about_registration(callback.bot, player)
    await callback.message.answer(
        f"{player.display_name}, заявка отправлена на проверку администратору."
    )
