from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from app.bot.telegram.formatters.statistics import profile as profile_fmt
from app.bot.telegram.handlers.user.shared import (
    delete_message as _delete_message,
)
from app.bot.telegram.keyboards import labels
from app.bot.telegram.keyboards.user import profile as user_profile_kb
from app.bot.telegram.message_edit import edit_message_if_changed
from app.bot.telegram.texts.user import profile as text
from app.services.access_policy import ActiveUserRequiredError
from app.services.pagination import pagination_service
from app.services.profile_service import (
    ProfileFutureSeasonError,
    ProfileKind,
    ProfileNotAllowedError,
    ProfileSeasonNotFoundError,
    profile_service,
)
from app.services.user_access_service import user_access_service

router = Router(name="user.profile")


@router.message(F.text == labels.MAIN_PROFILE)
async def show_profile_menu(message: Message) -> None:
    if message.from_user is None:
        return

    try:
        await user_access_service.require_active_user(message.from_user.id)
    except ActiveUserRequiredError:
        await message.answer(text.PROFILE_UNAVAILABLE)
        return

    await message.answer(
        text.PROFILE_MENU_PROMPT,
        reply_markup=user_profile_kb.profile_keyboard(),
    )


@router.callback_query(user_profile_kb.ProfileCallback.filter())
async def show_profile(
    callback: CallbackQuery,
    callback_data: user_profile_kb.ProfileCallback,
) -> None:
    try:
        title, stats = await profile_service.get_profile_for_player(
            telegram_id=callback.from_user.id,
            kind=callback_data.kind,
            season_id=getattr(callback_data, "season_id", 0) or None,
        )
    except ProfileNotAllowedError:
        await callback.answer(
            text.PROFILE_ACTIVE_ONLY,
            show_alert=True,
        )
        return
    except (ProfileSeasonNotFoundError, ProfileFutureSeasonError):
        await callback.answer("Сезон недоступен.", show_alert=True)
        return

    await callback.answer()
    if callback.message is not None:
        await edit_message_if_changed(
            callback.message,
            text=profile_fmt.message(title, stats),
            reply_markup=user_profile_kb.profile_result_keyboard(
                kind=callback_data.kind,
                season_page=getattr(callback_data, "season_page", 0),
            ),
        )


@router.callback_query(user_profile_kb.ProfileSeasonPageCallback.filter())
async def show_profile_season_picker(
    callback: CallbackQuery,
    callback_data: user_profile_kb.ProfileSeasonPageCallback,
) -> None:
    try:
        seasons = await profile_service.list_profile_seasons(callback.from_user.id)
    except ProfileNotAllowedError:
        await callback.answer(text.PROFILE_ACTIVE_ONLY, show_alert=True)
        return

    page = pagination_service.paginate(
        seasons,
        page=callback_data.page,
        page_size=user_profile_kb.PROFILE_SEASON_PAGE_SIZE,
    )
    await callback.answer()
    if callback.message is not None:
        await edit_message_if_changed(
            callback.message,
            text="Выбери сезон.",
            reply_markup=user_profile_kb.profile_seasons_keyboard(page),
        )


@router.callback_query(user_profile_kb.ProfileSeasonCallback.filter())
async def show_profile_for_selected_season(
    callback: CallbackQuery,
    callback_data: user_profile_kb.ProfileSeasonCallback,
) -> None:
    try:
        title, stats = await profile_service.get_profile_for_player(
            telegram_id=callback.from_user.id,
            kind=ProfileKind.SELECTED_SEASON,
            season_id=callback_data.season_id,
        )
    except ProfileNotAllowedError:
        await callback.answer(text.PROFILE_ACTIVE_ONLY, show_alert=True)
        return
    except (ProfileSeasonNotFoundError, ProfileFutureSeasonError):
        await callback.answer("Сезон недоступен.", show_alert=True)
        return

    await callback.answer()
    if callback.message is not None:
        await edit_message_if_changed(
            callback.message,
            text=profile_fmt.message(title, stats),
            reply_markup=user_profile_kb.profile_result_keyboard(
                kind=ProfileKind.SELECTED_SEASON,
                season_page=callback_data.season_page,
            ),
        )


@router.callback_query(user_profile_kb.ProfileCancelCallback.filter())
async def cancel_profile(
    callback: CallbackQuery,
    callback_data: user_profile_kb.ProfileCancelCallback | None = None,
) -> None:
    action = callback_data.action if callback_data is not None else "cancel"
    if action == "back":
        await callback.answer()
        if callback.message is not None:
            await edit_message_if_changed(
                callback.message,
                text=text.PROFILE_MENU_PROMPT,
                reply_markup=user_profile_kb.profile_keyboard(),
            )
        return

    answer = "Профиль закрыт" if action == "close" else "Отмена"
    await callback.answer(answer)
    if callback.message is None:
        return

    await _delete_message(callback.message)
    await callback.message.answer(answer)
