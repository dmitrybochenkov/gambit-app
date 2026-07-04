from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.telegram.keyboards.main import main_keyboard
from app.bot.telegram.keyboards.registration import (
    CONFIRM_REGISTRATION_CALLBACK,
    RESTART_REGISTRATION_CALLBACK,
    RegistrationModeCallback,
    registration_confirmation_keyboard,
    registration_mode_keyboard,
)
from app.bot.telegram.states import RegistrationMode, RegistrationStates
from app.db.models.enums import PlayerStatus
from app.services.player_service import (
    IdentityAlreadyExistsError,
    RegistrationNotAllowedError,
    player_service,
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
    await message.answer(REGISTRATION_GREETING, reply_markup=registration_mode_keyboard())


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
        await message.answer("Твоя заявка на регистрацию находится на проверке.")
        return

    if player.status == PlayerStatus.BLOCKED:
        await message.answer("Доступ к боту заблокирован.")
        return

    await message.answer(
        f"{player.display_name}, добро пожаловать!",
        reply_markup=main_keyboard(),
    )


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

    if callback_data.mode == RegistrationMode.NICKNAME:
        await state.set_state(RegistrationStates.entering_nickname)
        await callback.message.answer("Введи никнейм.")
        return

    await state.set_state(RegistrationStates.entering_full_name)
    await callback.message.answer("Введи фамилию и имя.")


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

    await state.update_data(full_name=full_name)
    data = await state.get_data()
    if data["mode"] == RegistrationMode.BOTH.value:
        await state.set_state(RegistrationStates.entering_nickname)
        await message.answer("Теперь введи никнейм.")
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

    await state.update_data(nickname=nickname)
    await _send_confirmation(message, state)


@router.callback_query(F.data == RESTART_REGISTRATION_CALLBACK)
async def restart_registration(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is None:
        return

    await state.clear()
    await _send_registration_intro(callback.message)


@router.callback_query(F.data == CONFIRM_REGISTRATION_CALLBACK)
async def confirm_registration(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is None:
        return

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
        await callback.message.answer("Эти данные уже заняты. Введи другое значение.")
        return
    except RegistrationNotAllowedError:
        await state.clear()
        await callback.message.answer("Повторная регистрация недоступна.")
        return

    await state.clear()
    await callback.message.answer(
        f"{player.display_name}, заявка отправлена на проверку администратору."
    )
