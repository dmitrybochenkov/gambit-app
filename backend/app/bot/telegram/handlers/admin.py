from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from app.bot.telegram import keyboards, texts
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
@router.message(F.text == keyboards.MAIN_ADMIN)
async def show_pending_registrations(message: Message) -> None:
    if message.from_user is None:
        return

    try:
        players = await player_service.get_pending_for_admin(message.from_user.id)
    except AdminAccessDeniedError:
        await message.answer(texts.admin.ACCESS_DENIED)
        return

    if not players:
        await message.answer(texts.admin.NO_PENDING_REGISTRATIONS)
        return

    await message.answer(texts.admin.pending_registrations_count(len(players)))
    for player in players:
        matches = await player_service.get_registration_matches(player.id)
        await message.answer(
            format_registration_review(player, matches),
            reply_markup=keyboards.registration_review_keyboard(
                player.id,
                has_matches=bool(matches),
            ),
        )


@router.callback_query(keyboards.RegistrationReviewCallback.filter())
async def review_registration(
    callback: CallbackQuery,
    callback_data: keyboards.RegistrationReviewCallback,
) -> None:
    try:
        if callback_data.action in {
            keyboards.RegistrationReviewAction.APPROVE,
            keyboards.RegistrationReviewAction.APPROVE_NEW,
        }:
            player = await player_service.approve_registration(
                admin_telegram_id=callback.from_user.id,
                player_id=callback_data.player_id,
                use_registration_match=(
                    callback_data.action == keyboards.RegistrationReviewAction.APPROVE
                ),
            )
            result_text = (
                texts.admin.REGISTRATION_APPROVED_AS_NEW
                if callback_data.action == keyboards.RegistrationReviewAction.APPROVE_NEW
                else texts.admin.REGISTRATION_APPROVED
            )
            player_text = texts.admin.registration_approved_message(
                player.display_name
            )
            player_keyboard = keyboards.main_keyboard()
        else:
            player = await player_service.reject_registration(
                admin_telegram_id=callback.from_user.id,
                player_id=callback_data.player_id,
            )
            result_text = texts.admin.REGISTRATION_REJECTED
            player_text = texts.admin.REGISTRATION_REJECTION_MESSAGE
            player_keyboard = ReplyKeyboardRemove()
    except AdminAccessDeniedError:
        await callback.answer(texts.admin.ACCESS_DENIED, show_alert=True)
        return
    except PlayerNotFoundError:
        await callback.answer(texts.admin.PLAYER_NOT_FOUND, show_alert=True)
        return
    except RegistrationAlreadyReviewedError:
        await callback.answer(
            texts.admin.REGISTRATION_ALREADY_REVIEWED,
            show_alert=True,
        )
        return

    await callback.answer(result_text)
    if callback.message is not None:
        try:
            await callback.message.edit_text(
                texts.admin.reviewed_by_admin(
                    review_text=callback.message.text or format_registration_review(player),
                    result_text=result_text,
                    admin_name=callback.from_user.full_name,
                )
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


@router.callback_query(keyboards.CalendarPromptCallback.filter())
async def review_calendar_prompt(
    callback: CallbackQuery,
    callback_data: keyboards.CalendarPromptCallback,
) -> None:
    action = CalendarPromptAction(callback_data.action.value)
    try:
        await calendar_service.resolve_prompt(
            prompt_id=callback_data.prompt_id,
            admin_telegram_id=callback.from_user.id,
            action=action,
        )
    except CalendarPromptNotFoundError:
        await callback.answer(texts.admin.CALENDAR_PROMPT_NOT_FOUND, show_alert=True)
        return
    except CalendarPromptAlreadyResolvedError:
        await callback.answer(
            texts.admin.CALENDAR_PROMPT_ALREADY_RESOLVED,
            show_alert=True,
        )
        return

    if callback_data.action == keyboards.CalendarPromptAction.CONFIRM:
        result_text = texts.admin.CALENDAR_PROMPT_CONFIRMED
    elif callback_data.action == keyboards.CalendarPromptAction.CANCEL:
        result_text = texts.admin.CALENDAR_PROMPT_CANCELLED
    else:
        result_text = texts.admin.CALENDAR_PROMPT_NEEDS_CHANGES

    await callback.answer(result_text)
    if callback.message is not None:
        try:
            await callback.message.edit_text(
                texts.admin.calendar_reviewed_by_admin(
                    prompt_text=callback.message.text or "",
                    result_text=result_text,
                    admin_name=callback.from_user.full_name,
                )
            )
        except TelegramBadRequest:
            pass
