import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.telegram.formatters import check_in as check_in_fmt
from app.bot.telegram.handlers.admin.shared import (
    delete_callback_message as _delete_callback_message,
)
from app.bot.telegram.keyboards import labels
from app.bot.telegram.keyboards.admin import check_in as admin_check_in_kb
from app.bot.telegram.keyboards.admin import panel as admin_panel_kb
from app.bot.telegram.keyboards.admin import results as admin_results_kb
from app.bot.telegram.message_edit import (
    edit_message_if_changed,
    edit_message_reply_markup_by_id_if_changed,
)
from app.bot.telegram.states import AdminResultStates
from app.bot.telegram.texts.admin import panel as panel_text
from app.bot.telegram.texts.admin import results as result_text
from app.services.access_policy import AdminAccessDeniedError
from app.services.pagination import pagination_service
from app.services.player_reward_service import (
    PlayerRewardAlreadyRedeemedTodayError,
    PlayerRewardNotFoundError,
    player_reward_service,
)
from app.services.tournament_check_in_service import (
    CheckInResultView,
    TournamentCheckInClosedError,
    TournamentCheckInDuplicateNameError,
    TournamentCheckInNotFoundError,
    TournamentCheckInRegisteredUserError,
    TournamentCheckInUserNotFoundError,
    tournament_check_in_service,
)
from app.services.user_access_service import user_access_service

logger = logging.getLogger(__name__)


router = Router(name="admin.check_in")


@router.message(F.text == labels.ADMIN_PANEL_CHECK_IN)
async def show_admin_check_in(message: Message) -> None:
    if message.from_user is None:
        return

    try:
        tournaments = await tournament_check_in_service.list_today_tournaments(message.from_user.id)
    except AdminAccessDeniedError:
        await message.answer(panel_text.ACCESS_DENIED)
        return

    if not tournaments:
        await message.answer("На сегодня нет активного турнира.")
        return

    if len(tournaments) > 1:
        page = pagination_service.paginate(
            tournaments,
            page=0,
            page_size=admin_results_kb.ADMIN_RESULT_PAGE_SIZE,
        )
        await message.answer(
            check_in_fmt.tournament_list(page),
            reply_markup=admin_results_kb.admin_result_tournament_list_keyboard(page),
        )
        return

    view = await tournament_check_in_service.get_check_in(
        admin_telegram_id=message.from_user.id,
        tournament_id=tournaments[0].id,
    )
    await message.answer(
        check_in_fmt.summary(view),
        reply_markup=admin_check_in_kb.admin_check_in_keyboard(view),
    )


@router.callback_query(admin_check_in_kb.AdminCheckInCallback.filter())
async def select_check_in_action(
    callback: CallbackQuery,
    callback_data: admin_check_in_kb.AdminCheckInCallback,
    state: FSMContext,
) -> None:
    try:
        if callback_data.action == admin_check_in_kb.AdminCheckInAction.CANCEL:
            await state.clear()
            await callback.answer(result_text.ADMIN_RESULTS_CANCELLED)
            await _return_to_admin_menu(callback, result_text.ADMIN_RESULTS_CANCELLED)
            return

        if callback_data.action == admin_check_in_kb.AdminCheckInAction.BACK:
            await callback.answer()
            if callback.message is not None and await _restore_check_in_previous_screen(
                callback=callback,
                state=state,
                tournament_id=callback_data.tournament_id,
            ):
                return

        if callback_data.action in {
            admin_check_in_kb.AdminCheckInAction.BACK,
            admin_check_in_kb.AdminCheckInAction.BACK_TO_TOURNAMENT,
        }:
            if callback_data.action == admin_check_in_kb.AdminCheckInAction.BACK_TO_TOURNAMENT:
                await callback.answer()
            await state.clear()
            view = await tournament_check_in_service.get_check_in(
                admin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
            )
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=check_in_fmt.summary(view),
                    reply_markup=admin_check_in_kb.admin_check_in_keyboard(view),
                )
            return

        if callback_data.action == admin_check_in_kb.AdminCheckInAction.SHOW_CHECKED_IN:
            view = await tournament_check_in_service.get_checked_in_players(
                admin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
            )
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=check_in_fmt.checked_in_players(view),
                    reply_markup=admin_check_in_kb.admin_checked_in_players_keyboard(
                        callback_data.tournament_id
                    ),
                )
            return

        if callback_data.action == admin_check_in_kb.AdminCheckInAction.SELECT_REWARD:
            rewards = await player_reward_service.list_active_rewards_for_check_in(
                admin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
                player_id=callback_data.player_id,
            )
            confirmation = await tournament_check_in_service.get_user_check_in_confirmation(
                admin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
                user_id=callback_data.player_id,
            )
            result = CheckInResultView(
                confirmation.tournament,
                confirmation.user,
                True,
                rewards,
            )
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=check_in_fmt.reward_selection(result),
                    reply_markup=admin_check_in_kb.admin_check_in_reward_selection_keyboard(
                        tournament_id=callback_data.tournament_id,
                        player_id=callback_data.player_id,
                        rewards=rewards,
                    ),
                )
            return

        if callback_data.action == admin_check_in_kb.AdminCheckInAction.CONFIRM_REWARD:
            reward = await player_reward_service.get_active_reward_for_player(
                admin_telegram_id=callback.from_user.id,
                player_id=callback_data.player_id,
                reward_id=callback_data.reward_id,
            )
            confirmation = await tournament_check_in_service.get_user_check_in_confirmation(
                admin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
                user_id=callback_data.player_id,
            )
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=check_in_fmt.reward_confirmation(confirmation.user, reward),
                    reply_markup=admin_check_in_kb.admin_check_in_reward_confirmation_keyboard(
                        tournament_id=callback_data.tournament_id,
                        player_id=callback_data.player_id,
                        reward_id=callback_data.reward_id,
                    ),
                )
            return

        if callback_data.action in {
            admin_check_in_kb.AdminCheckInAction.SKIP_REWARD,
            admin_check_in_kb.AdminCheckInAction.REDEEM_REWARD,
        }:
            if callback_data.action == admin_check_in_kb.AdminCheckInAction.REDEEM_REWARD:
                reward = await player_reward_service.redeem_reward(
                    admin_telegram_id=callback.from_user.id,
                    tournament_id=callback_data.tournament_id,
                    reward_id=callback_data.reward_id,
                )
                message_text = check_in_fmt.reward_redeemed(reward)
            else:
                message_text = "Бонус не использован."
            view = await tournament_check_in_service.get_check_in(
                admin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
            )
            await state.clear()
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(callback.message, text=message_text)
                await callback.message.answer(
                    check_in_fmt.summary(view),
                    reply_markup=admin_check_in_kb.admin_check_in_keyboard(view),
                )
            return

        if callback_data.action == admin_check_in_kb.AdminCheckInAction.REGISTERED_SEARCH:
            await state.set_state(AdminResultStates.entering_registered_check_in_search)
            await state.update_data(check_in_tournament_id=callback_data.tournament_id)
            await callback.answer()
            if callback.message is not None:
                await _delete_callback_message(callback)
                prompt = await callback.message.answer(
                    "Введи имя зарегистрированного игрока.",
                    reply_markup=admin_check_in_kb.admin_check_in_cancel_keyboard(
                        callback_data.tournament_id
                    ),
                )
                await state.update_data(check_in_prompt_message_id=prompt.message_id)
            return

        if callback_data.action == admin_check_in_kb.AdminCheckInAction.DATABASE_SEARCH:
            await state.set_state(AdminResultStates.entering_database_check_in_search)
            await state.update_data(check_in_tournament_id=callback_data.tournament_id)
            await callback.answer()
            if callback.message is not None:
                await _delete_callback_message(callback)
                prompt = await callback.message.answer(
                    "Введи имя игрока из базы.",
                    reply_markup=admin_check_in_kb.admin_check_in_cancel_keyboard(
                        callback_data.tournament_id
                    ),
                )
                await state.update_data(check_in_prompt_message_id=prompt.message_id)
            return

        if callback_data.action == admin_check_in_kb.AdminCheckInAction.NEW_PLAYER:
            await state.set_state(AdminResultStates.entering_new_check_in_player)
            await state.update_data(check_in_tournament_id=callback_data.tournament_id)
            await callback.answer()
            if callback.message is not None:
                await _delete_callback_message(callback)
                prompt = await callback.message.answer(
                    "Введи имя нового игрока.",
                    reply_markup=admin_check_in_kb.admin_check_in_cancel_keyboard(
                        callback_data.tournament_id
                    ),
                )
                await state.update_data(check_in_prompt_message_id=prompt.message_id)
            return

        if callback_data.action == admin_check_in_kb.AdminCheckInAction.CONFIRM_REGISTERED:
            confirmation = await tournament_check_in_service.get_user_check_in_confirmation(
                admin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
                user_id=callback_data.player_id,
            )
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=check_in_fmt.registered_confirmation(
                        confirmation.tournament,
                        confirmation.user,
                    ),
                    reply_markup=admin_check_in_kb.admin_check_in_confirmation_keyboard(
                        tournament_id=callback_data.tournament_id,
                        player_id=callback_data.player_id,
                        confirm_action=admin_check_in_kb.AdminCheckInAction.ADD_REGISTERED,
                    ),
                )
            return

        if callback_data.action == admin_check_in_kb.AdminCheckInAction.CONFIRM_EXISTING:
            confirmation = await tournament_check_in_service.get_user_check_in_confirmation(
                admin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
                user_id=callback_data.player_id,
            )
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=check_in_fmt.existing_confirmation(
                        confirmation.tournament,
                        confirmation.user,
                    ),
                    reply_markup=admin_check_in_kb.admin_check_in_confirmation_keyboard(
                        tournament_id=callback_data.tournament_id,
                        player_id=callback_data.player_id,
                        confirm_action=admin_check_in_kb.AdminCheckInAction.ADD_EXISTING,
                    ),
                )
            return

        if callback_data.action == admin_check_in_kb.AdminCheckInAction.CONFIRM_NEW:
            data = await state.get_data()
            display_name = str(data.get("new_check_in_display_name", ""))
            (
                tournament,
                display_name,
            ) = await tournament_check_in_service.get_new_user_check_in_confirmation(
                admin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
                display_name=display_name,
            )
            await state.set_state(AdminResultStates.confirming_new_check_in_player)
            await state.update_data(
                check_in_tournament_id=callback_data.tournament_id,
                new_check_in_display_name=display_name,
            )
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=check_in_fmt.new_confirmation(tournament, display_name),
                    reply_markup=admin_check_in_kb.admin_check_in_confirmation_keyboard(
                        tournament_id=callback_data.tournament_id,
                        confirm_action=admin_check_in_kb.AdminCheckInAction.CREATE_NEW,
                        confirm_text="✅ Создать",
                    ),
                )
            return

        if callback_data.action == admin_check_in_kb.AdminCheckInAction.ADD_REGISTERED:
            result = await tournament_check_in_service.check_in_registered(
                admin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
                user_id=callback_data.player_id,
            )
        elif callback_data.action == admin_check_in_kb.AdminCheckInAction.ADD_EXISTING:
            result = await tournament_check_in_service.check_in_existing_user(
                admin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
                user_id=callback_data.player_id,
            )
        elif callback_data.action == admin_check_in_kb.AdminCheckInAction.CREATE_NEW:
            data = await state.get_data()
            result = await tournament_check_in_service.create_user_and_check_in(
                admin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
                display_name=str(data.get("new_check_in_display_name", "")),
            )
        else:
            await callback.answer(result_text.ADMIN_RESULTS_NOT_FOUND, show_alert=True)
            return
        view = await tournament_check_in_service.get_check_in(
            admin_telegram_id=callback.from_user.id,
            tournament_id=callback_data.tournament_id,
        )
    except AdminAccessDeniedError:
        await state.clear()
        await callback.answer(panel_text.ACCESS_DENIED, show_alert=True)
        return
    except (
        TournamentCheckInNotFoundError,
        TournamentCheckInClosedError,
        TournamentCheckInUserNotFoundError,
    ):
        await callback.answer(result_text.ADMIN_RESULTS_NOT_FOUND, show_alert=True)
        return
    except TournamentCheckInDuplicateNameError:
        await callback.answer("Игрок с таким именем уже существует.", show_alert=True)
        return
    except TournamentCheckInRegisteredUserError:
        await callback.answer(
            "Игрок зарегистрирован на этот турнир.\n"
            "Используйте check-in зарегистрированного игрока.",
            show_alert=True,
        )
        return
    except PlayerRewardNotFoundError:
        await callback.answer("Бонус больше недоступен.", show_alert=True)
        return
    except PlayerRewardAlreadyRedeemedTodayError:
        await callback.answer("Сегодня уже использован другой бонус.", show_alert=True)
        return

    await state.clear()
    await callback.answer(
        result_text.ADMIN_RESULTS_SAVED if result.created else "Игрок уже прошёл check-in."
    )
    await _send_check_in_notification(callback, result)
    if result.created and result.active_rewards:
        if callback.message is not None:
            await edit_message_if_changed(
                callback.message,
                text=check_in_fmt.reward_selection(result),
                reply_markup=admin_check_in_kb.admin_check_in_reward_selection_keyboard(
                    tournament_id=callback_data.tournament_id,
                    player_id=result.user.id,
                    rewards=result.active_rewards,
                ),
            )
        return
    if callback.message is not None:
        await edit_message_if_changed(
            callback.message,
            text=check_in_fmt.admin_success(result.tournament, result.user),
        )
        await callback.message.answer(
            check_in_fmt.summary(view),
            reply_markup=admin_check_in_kb.admin_check_in_keyboard(view),
        )


async def _send_check_in_notification(
    callback: CallbackQuery,
    result: CheckInResultView,
) -> None:
    if not result.created:
        return
    user = result.user
    if user.telegram_id is None:
        return
    try:
        await callback.bot.send_message(
            chat_id=user.telegram_id,
            text=check_in_fmt.player_notification(result.tournament),
        )
    except (TelegramBadRequest, TelegramForbiddenError):
        logger.info("Failed to send check-in notification", exc_info=True)


async def _return_to_admin_menu(callback: CallbackQuery, message_text: str) -> None:
    if callback.message is None:
        return
    admin_panel = await user_access_service.get_admin_panel_for_admin(callback.from_user.id)
    await _delete_callback_message(callback)
    await callback.message.answer(
        message_text,
        reply_markup=admin_panel_kb.admin_panel_keyboard(admin_panel.admin),
    )


async def _restore_check_in_previous_screen(
    *,
    callback: CallbackQuery,
    state: FSMContext,
    tournament_id: int,
) -> bool:
    data = await state.get_data()
    back_screen = data.get("check_in_back")
    query = str(data.get("check_in_query", ""))
    if back_screen == "registered_search":
        players = await tournament_check_in_service.search_registered(
            admin_telegram_id=callback.from_user.id,
            tournament_id=tournament_id,
            query=query,
        )
        await edit_message_if_changed(
            callback.message,
            text="Нашел среди зарегистрированных:" if players else "Игроки не найдены.",
            reply_markup=admin_check_in_kb.admin_check_in_search_results_keyboard(
                tournament_id=tournament_id,
                players=players,
                action=admin_check_in_kb.AdminCheckInAction.CONFIRM_REGISTERED,
                back_action=admin_check_in_kb.AdminCheckInAction.REGISTERED_SEARCH,
            )
            if players
            else None,
        )
        return True
    if back_screen == "database_search":
        players = await tournament_check_in_service.search_users(
            admin_telegram_id=callback.from_user.id,
            tournament_id=tournament_id,
            query=query,
        )
        await edit_message_if_changed(
            callback.message,
            text="Нашел игроков в базе:" if players else "Игроки не найдены.",
            reply_markup=admin_check_in_kb.admin_check_in_search_results_keyboard(
                tournament_id=tournament_id,
                players=players,
                action=admin_check_in_kb.AdminCheckInAction.CONFIRM_EXISTING,
                back_action=admin_check_in_kb.AdminCheckInAction.DATABASE_SEARCH,
            )
            if players
            else None,
        )
        return True
    if back_screen == "new_player_candidates":
        display_name = str(data.get("new_check_in_display_name", ""))
        _, candidates, exact_exists = await tournament_check_in_service.find_new_player_candidates(
            admin_telegram_id=callback.from_user.id,
            tournament_id=tournament_id,
            display_name=display_name,
        )
        if exact_exists and candidates:
            await edit_message_if_changed(
                callback.message,
                text="Игрок с таким именем уже существует.",
                reply_markup=admin_check_in_kb.admin_check_in_exact_match_keyboard(
                    tournament_id=tournament_id,
                    user_id=candidates[0].id,
                ),
            )
            return True
        await edit_message_if_changed(
            callback.message,
            text="В базе найдены похожие игроки:",
            reply_markup=admin_check_in_kb.admin_check_in_similar_players_keyboard(
                tournament_id=tournament_id,
                players=candidates,
            ),
        )
        return True
    if back_screen == "new_player_prompt":
        await state.set_state(AdminResultStates.entering_new_check_in_player)
        await edit_message_if_changed(
            callback.message,
            text="Введи имя нового игрока.",
            reply_markup=admin_check_in_kb.admin_check_in_cancel_keyboard(tournament_id),
        )
        await state.update_data(check_in_prompt_message_id=callback.message.message_id)
        return True
    return False


@router.message(AdminResultStates.entering_registered_check_in_search)
async def enter_registered_check_in_search(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return
    data = await state.get_data()
    tournament_id = int(data["check_in_tournament_id"])
    query = message.text or ""
    await _clear_check_in_prompt_markup(message, data)
    try:
        players = await tournament_check_in_service.search_registered(
            admin_telegram_id=message.from_user.id,
            tournament_id=tournament_id,
            query=query,
        )
    except AdminAccessDeniedError:
        await state.clear()
        await message.answer(panel_text.ACCESS_DENIED)
        return
    except (TournamentCheckInNotFoundError, TournamentCheckInClosedError):
        await state.clear()
        await message.answer(result_text.ADMIN_RESULTS_NOT_FOUND)
        return

    if not players:
        await state.update_data(
            check_in_tournament_id=tournament_id,
            check_in_back="registered_search",
            check_in_query=query,
        )
        await message.answer(
            "Игроки не найдены.",
            reply_markup=admin_check_in_kb.admin_check_in_empty_search_keyboard(
                tournament_id=tournament_id,
                search_action=admin_check_in_kb.AdminCheckInAction.REGISTERED_SEARCH,
            ),
        )
        return
    await state.update_data(
        check_in_tournament_id=tournament_id,
        check_in_back="registered_search",
        check_in_query=query,
    )
    await message.answer(
        "Нашел среди зарегистрированных:",
        reply_markup=admin_check_in_kb.admin_check_in_search_results_keyboard(
            tournament_id=tournament_id,
            players=players,
            action=admin_check_in_kb.AdminCheckInAction.CONFIRM_REGISTERED,
            back_action=admin_check_in_kb.AdminCheckInAction.REGISTERED_SEARCH,
        ),
    )


@router.message(AdminResultStates.entering_database_check_in_search)
async def enter_database_check_in_search(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return
    data = await state.get_data()
    tournament_id = int(data["check_in_tournament_id"])
    query = message.text or ""
    await _clear_check_in_prompt_markup(message, data)
    try:
        players = await tournament_check_in_service.search_users(
            admin_telegram_id=message.from_user.id,
            tournament_id=tournament_id,
            query=query,
        )
    except AdminAccessDeniedError:
        await state.clear()
        await message.answer(panel_text.ACCESS_DENIED)
        return
    except (TournamentCheckInNotFoundError, TournamentCheckInClosedError):
        await state.clear()
        await message.answer(result_text.ADMIN_RESULTS_NOT_FOUND)
        return

    if not players:
        await state.update_data(
            check_in_tournament_id=tournament_id,
            check_in_back="database_search",
            check_in_query=query,
        )
        await message.answer(
            "Игроки не найдены.",
            reply_markup=admin_check_in_kb.admin_check_in_empty_search_keyboard(
                tournament_id=tournament_id,
                search_action=admin_check_in_kb.AdminCheckInAction.DATABASE_SEARCH,
            ),
        )
        return
    await state.update_data(
        check_in_tournament_id=tournament_id,
        check_in_back="database_search",
        check_in_query=query,
    )
    await message.answer(
        "Нашел игроков в базе:",
        reply_markup=admin_check_in_kb.admin_check_in_search_results_keyboard(
            tournament_id=tournament_id,
            players=players,
            action=admin_check_in_kb.AdminCheckInAction.CONFIRM_EXISTING,
            back_action=admin_check_in_kb.AdminCheckInAction.DATABASE_SEARCH,
        ),
    )


@router.message(AdminResultStates.entering_new_check_in_player)
async def enter_new_check_in_player(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return
    data = await state.get_data()
    tournament_id = int(data["check_in_tournament_id"])
    display_name = message.text or ""
    await _clear_check_in_prompt_markup(message, data)
    try:
        (
            normalized,
            candidates,
            exact_exists,
        ) = await tournament_check_in_service.find_new_player_candidates(
            admin_telegram_id=message.from_user.id,
            tournament_id=tournament_id,
            display_name=display_name,
        )
        await state.update_data(
            check_in_tournament_id=tournament_id,
            new_check_in_display_name=display_name,
            new_check_in_display_name_normalized=normalized,
            check_in_back="new_player_candidates",
        )
        (
            tournament,
            display_name,
        ) = await tournament_check_in_service.get_new_user_check_in_confirmation(
            admin_telegram_id=message.from_user.id,
            tournament_id=tournament_id,
            display_name=display_name,
        )
    except AdminAccessDeniedError:
        await state.clear()
        await message.answer(panel_text.ACCESS_DENIED)
        return
    except (TournamentCheckInNotFoundError, TournamentCheckInClosedError):
        await state.clear()
        await message.answer(result_text.ADMIN_RESULTS_NOT_FOUND)
        return
    except ValueError:
        await message.answer("Имя игрока некорректное.")
        return

    if exact_exists:
        exact_candidate = candidates[0]
        await message.answer(
            "Игрок с таким именем уже существует.",
            reply_markup=admin_check_in_kb.admin_check_in_exact_match_keyboard(
                tournament_id=tournament_id,
                user_id=exact_candidate.id,
            ),
        )
        return
    if candidates:
        await message.answer(
            "В базе найдены похожие игроки:",
            reply_markup=admin_check_in_kb.admin_check_in_similar_players_keyboard(
                tournament_id=tournament_id,
                players=candidates,
            ),
        )
        return

    await state.set_state(AdminResultStates.confirming_new_check_in_player)
    await state.update_data(check_in_back="new_player_prompt")
    await message.answer(
        check_in_fmt.new_confirmation(tournament, display_name),
        reply_markup=admin_check_in_kb.admin_check_in_confirmation_keyboard(
            tournament_id=tournament_id,
            confirm_action=admin_check_in_kb.AdminCheckInAction.CREATE_NEW,
            confirm_text="✅ Создать",
        ),
    )


async def _clear_check_in_prompt_markup(message: Message, data: dict[str, object]) -> None:
    prompt_message_id = int(data.get("check_in_prompt_message_id") or 0)
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
        logger.info("Failed to clear check-in prompt markup", exc_info=True)
