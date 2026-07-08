from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from app.bot.telegram.keyboards.admin import (
    CalendarPromptAction as KeyboardCalendarPromptAction,
)
from app.bot.telegram.keyboards.admin import (
    CalendarPromptCallback,
    RegistrationReviewAction,
    RegistrationReviewCallback,
    registration_review_keyboard,
)
from app.bot.telegram.keyboards.main import main_keyboard
from app.bot.telegram.notifications import format_registration_review
from app.services.calendar_service import (
    CalendarPromptAction,
    CalendarPromptAlreadyResolvedError,
    CalendarPromptNotFoundError,
    calendar_service,
)
from app.services.player_service import (
    AdminAccessDeniedError,
    PlayerNotFoundError,
    RegistrationAlreadyReviewedError,
    player_service,
)

router = Router(name="admin")


@router.message(Command("admin"))
@router.message(F.text == "Админ-панель")
async def show_pending_registrations(message: Message) -> None:
    if message.from_user is None:
        return

    try:
        players = await player_service.get_pending_for_admin(message.from_user.id)
    except AdminAccessDeniedError:
        await message.answer("Недостаточно прав.")
        return

    if not players:
        await message.answer("Новых заявок нет.")
        return

    await message.answer(f"Заявок на проверке: {len(players)}")
    for player in players:
        await message.answer(
            format_registration_review(player),
            reply_markup=registration_review_keyboard(player.id),
        )


@router.callback_query(RegistrationReviewCallback.filter())
async def review_registration(
    callback: CallbackQuery,
    callback_data: RegistrationReviewCallback,
) -> None:
    try:
        if callback_data.action == RegistrationReviewAction.APPROVE:
            player = await player_service.approve_registration(
                admin_telegram_id=callback.from_user.id,
                player_id=callback_data.player_id,
            )
            result_text = "Заявка одобрена"
            player_text = f"{player.display_name}, ты успешно зарегистрирован/а!"
            player_keyboard = main_keyboard()
        else:
            player = await player_service.reject_registration(
                admin_telegram_id=callback.from_user.id,
                player_id=callback_data.player_id,
            )
            result_text = "Заявка отклонена"
            player_text = "Ты не зарегистрирован/а. Попробуй другой никнейм или имя через /start."
            player_keyboard = ReplyKeyboardRemove()
    except AdminAccessDeniedError:
        await callback.answer("Недостаточно прав.", show_alert=True)
        return
    except PlayerNotFoundError:
        await callback.answer("Игрок не найден.", show_alert=True)
        return
    except RegistrationAlreadyReviewedError:
        await callback.answer("Заявка уже обработана.", show_alert=True)
        return

    await callback.answer(result_text)
    if callback.message is not None:
        try:
            await callback.message.edit_text(
                f"{format_registration_review(player)}\n\n{result_text}: "
                f"{callback.from_user.full_name}"
            )
        except TelegramBadRequest:
            pass

    try:
        await callback.bot.send_message(
            chat_id=player.telegram_id,
            text=player_text,
            reply_markup=player_keyboard,
        )
    except (TelegramBadRequest, TelegramForbiddenError):
        pass


@router.callback_query(CalendarPromptCallback.filter())
async def review_calendar_prompt(
    callback: CallbackQuery,
    callback_data: CalendarPromptCallback,
) -> None:
    action = CalendarPromptAction(callback_data.action.value)
    try:
        await calendar_service.resolve_prompt(
            prompt_id=callback_data.prompt_id,
            admin_telegram_id=callback.from_user.id,
            action=action,
        )
    except CalendarPromptNotFoundError:
        await callback.answer("Предложение не найдено.", show_alert=True)
        return
    except CalendarPromptAlreadyResolvedError:
        await callback.answer("Предложение уже обработано.", show_alert=True)
        return

    if callback_data.action == KeyboardCalendarPromptAction.CONFIRM:
        result_text = "Подтверждено"
    elif callback_data.action == KeyboardCalendarPromptAction.CANCEL:
        result_text = "Отменено"
    else:
        result_text = "Нужны правки. Ручное редактирование добавим в админке."

    await callback.answer(result_text)
    if callback.message is not None:
        try:
            await callback.message.edit_text(
                f"{callback.message.text}\n\n{result_text}: "
                f"{callback.from_user.full_name}"
            )
        except TelegramBadRequest:
            pass
