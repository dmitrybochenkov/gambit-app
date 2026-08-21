from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from app.bot.telegram.formatters.statistics import history as history_fmt
from app.bot.telegram.formatters.statistics import profile as profile_fmt
from app.bot.telegram.handlers.user.shared import (
    delete_message as _delete_message,
)
from app.bot.telegram.keyboards import labels
from app.bot.telegram.keyboards.user import history as user_history_kb
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
from app.services.user_statistics_service import (
    HistoricalTournamentNotFoundError,
    HistoryNotAllowedError,
    user_statistics_service,
)

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
        has_details = stats is not None and await _has_prize_tournaments(
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
                show_details=has_details,
                season_id=getattr(callback_data, "season_id", 0),
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
        has_details = stats is not None and await _has_prize_tournaments(
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
                show_details=has_details,
                season_id=callback_data.season_id,
                season_page=callback_data.season_page,
            ),
        )


@router.callback_query(user_profile_kb.ProfileDetailsPageCallback.filter())
async def show_profile_prize_tournaments(
    callback: CallbackQuery,
    callback_data: user_profile_kb.ProfileDetailsPageCallback,
) -> None:
    try:
        tournaments = await profile_service.list_prize_tournaments_for_player(
            telegram_id=callback.from_user.id,
            kind=callback_data.kind,
            season_id=callback_data.season_id or None,
        )
    except ProfileNotAllowedError:
        await callback.answer(text.PROFILE_ACTIVE_ONLY, show_alert=True)
        return
    except (ProfileSeasonNotFoundError, ProfileFutureSeasonError):
        await callback.answer("Сезон недоступен.", show_alert=True)
        return

    page = pagination_service.paginate(
        tournaments,
        page=callback_data.page,
        page_size=user_profile_kb.PROFILE_PRIZE_TOURNAMENT_PAGE_SIZE,
    )
    await callback.answer()
    if callback.message is not None:
        await edit_message_if_changed(
            callback.message,
            text=profile_fmt.prize_tournaments(page),
            reply_markup=user_profile_kb.profile_prize_tournaments_keyboard(
                page,
                kind=callback_data.kind,
                season_id=callback_data.season_id,
                season_page=callback_data.season_page,
            ),
        )


@router.callback_query(user_profile_kb.ProfilePrizeTournamentCallback.filter())
async def show_profile_prize_tournament_result(
    callback: CallbackQuery,
    callback_data: user_profile_kb.ProfilePrizeTournamentCallback,
) -> None:
    try:
        result = await user_statistics_service.get_historical_tournament_result(
            telegram_id=callback.from_user.id,
            tournament_id=callback_data.tournament_id,
        )
    except HistoryNotAllowedError:
        await callback.answer(text.PROFILE_ACTIVE_ONLY, show_alert=True)
        return
    except HistoricalTournamentNotFoundError:
        await callback.answer("Турнир недоступен.", show_alert=True)
        return

    page = pagination_service.paginate(
        result.rows,
        page=callback_data.result_page,
        page_size=user_history_kb.HISTORY_RESULT_PAGE_SIZE,
    )
    await callback.answer()
    if callback.message is not None:
        await edit_message_if_changed(
            callback.message,
            text=history_fmt.tournament_result(result, page),
            reply_markup=user_profile_kb.profile_history_result_keyboard(
                page,
                tournament_id=callback_data.tournament_id,
                kind=callback_data.kind,
                season_id=callback_data.season_id,
                season_page=callback_data.season_page,
                list_page=callback_data.list_page,
            ),
            parse_mode="Markdown",
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


async def _has_prize_tournaments(
    *,
    telegram_id: int,
    kind: ProfileKind,
    season_id: int | None,
) -> bool:
    tournaments = await profile_service.list_prize_tournaments_for_player(
        telegram_id=telegram_id,
        kind=kind,
        season_id=season_id,
    )
    return bool(tournaments)
