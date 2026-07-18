import re
from datetime import date
from decimal import Decimal, InvalidOperation

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from app.bot.telegram import keyboards, texts
from app.bot.telegram.formatters import (
    format_admin_calendar_prompt,
    format_admin_result_menu,
    format_admin_result_players,
    format_admin_result_tournament_list,
    format_created_season_prompt,
    format_created_tournaments_prompt,
    format_manual_season_prompt,
)
from app.bot.telegram.notifications import format_registration_review
from app.bot.telegram.states import (
    AdminResultStates,
    CalendarSeasonEditStates,
    CalendarTournamentEditStates,
)
from app.services.calendar_service import (
    CalendarPromptAction,
    CalendarPromptAlreadyResolvedError,
    CalendarPromptEmptyError,
    CalendarPromptInvalidPayloadError,
    CalendarPromptNotFoundError,
    calendar_service,
)
from app.services.dto import RegistrationReviewResultView
from app.services.pagination import pagination_service
from app.services.player_service import (
    AdminAccessDeniedError,
    PlayerNotFoundError,
    PlayerRoleAlreadyAssignedError,
    RegistrationAlreadyReviewedError,
    RegistrationMatchNotFoundError,
    player_service,
)
from app.services.result_service import (
    ResultInvalidPlayerDataError,
    ResultInvalidPoolError,
    ResultPlayerNotFoundError,
    ResultTournamentNotFoundError,
    ResultValidationError,
    result_service,
)

router = Router(name="admin")
SEASON_EDIT_PROMPTS = {
    keyboards.SeasonEditAction.NAME: texts.admin.ADMIN_CALENDAR_ENTER_SEASON_NAME,
    keyboards.SeasonEditAction.STARTS_AT: texts.admin.ADMIN_CALENDAR_ENTER_SEASON_START,
    keyboards.SeasonEditAction.ENDS_AT: texts.admin.ADMIN_CALENDAR_ENTER_SEASON_END,
}
TOURNAMENT_ECONOMY_PROMPT = (
    "Введи вход и аддон в формате:\n"
    "600 - 20000 - 800 - 125000"
)
TOURNAMENT_REBUYS_PROMPT = (
    "Введи ребаи в формате:\n"
    "600 / 800 / 800 / 800 / 1000 / 1000 - "
    "30000 / 50000 / 70000 / 90000 / 100000 / 100000"
)


@router.message(Command("admin"))
@router.message(F.text == keyboards.MAIN_ADMIN)
async def open_admin_panel(message: Message) -> None:
    if message.from_user is None:
        return

    try:
        await player_service.get_admin_panel_for_admin(message.from_user.id)
    except AdminAccessDeniedError:
        await message.answer(texts.admin.ACCESS_DENIED)
        return

    await message.answer(
        texts.admin.ADMIN_PANEL_WELCOME,
        reply_markup=keyboards.admin_panel_keyboard(),
    )


@router.message(F.text == keyboards.ADMIN_PANEL_REGISTRATIONS)
async def show_pending_registrations(message: Message) -> None:
    if message.from_user is None:
        return

    try:
        admin_panel = await player_service.get_admin_panel_for_admin(message.from_user.id)
    except AdminAccessDeniedError:
        await message.answer(texts.admin.ACCESS_DENIED)
        return

    reviews = admin_panel.reviews
    if not reviews:
        await message.answer(texts.admin.NO_PENDING_REGISTRATIONS)
        return

    page = pagination_service.paginate(
        reviews,
        page=0,
        page_size=keyboards.REGISTRATION_LIST_PAGE_SIZE,
    )
    await message.answer(
        texts.admin.registration_list(page),
        reply_markup=keyboards.registration_list_keyboard(page),
    )


@router.message(F.text == keyboards.ADMIN_PANEL_ADD_ADMIN)
async def show_admin_candidates(message: Message) -> None:
    if message.from_user is None:
        return

    try:
        players = await player_service.list_admin_candidates_for_superadmin(
            message.from_user.id
        )
    except AdminAccessDeniedError:
        await message.answer(texts.admin.INSUFFICIENT_RIGHTS)
        return

    if not players:
        await message.answer(texts.admin.ADMIN_ADD_NO_CANDIDATES)
        return

    page = pagination_service.paginate(
        players,
        page=0,
        page_size=keyboards.ADMIN_CANDIDATE_PAGE_SIZE,
    )
    await message.answer(
        texts.admin.admin_candidate_list(page),
        reply_markup=keyboards.admin_candidate_list_keyboard(page),
    )


@router.message(F.text == keyboards.ADMIN_PANEL_RESULTS)
async def show_result_tournaments(message: Message) -> None:
    if message.from_user is None:
        return

    try:
        tournaments = await result_service.list_todays_tournaments_for_admin(
            message.from_user.id
        )
    except AdminAccessDeniedError:
        await message.answer(texts.admin.ACCESS_DENIED)
        return

    if not tournaments:
        await message.answer(texts.admin.ADMIN_RESULTS_NO_TOURNAMENTS)
        return

    page = pagination_service.paginate(
        tournaments,
        page=0,
        page_size=keyboards.ADMIN_RESULT_PAGE_SIZE,
    )
    await message.answer(
        format_admin_result_tournament_list(page),
        reply_markup=keyboards.admin_result_tournament_list_keyboard(page),
    )


@router.callback_query(keyboards.AdminResultTournamentCallback.filter())
async def select_result_tournament(
    callback: CallbackQuery,
    callback_data: keyboards.AdminResultTournamentCallback,
    state: FSMContext,
) -> None:
    try:
        if callback_data.action == keyboards.AdminResultTournamentAction.CANCEL:
            await state.clear()
            await callback.answer(texts.admin.ADMIN_RESULTS_CANCELLED)
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer(texts.admin.ADMIN_RESULTS_CANCELLED)
            return

        tournaments = await result_service.list_todays_tournaments_for_admin(
            callback.from_user.id
        )
        if callback_data.action == keyboards.AdminResultTournamentAction.PAGE:
            page = pagination_service.paginate(
                tournaments,
                page=callback_data.page,
                page_size=keyboards.ADMIN_RESULT_PAGE_SIZE,
            )
            await callback.answer()
            if callback.message is not None:
                await callback.message.edit_text(
                    format_admin_result_tournament_list(page),
                    reply_markup=keyboards.admin_result_tournament_list_keyboard(page),
                )
            return

        draft = await result_service.get_or_create_draft(
            admin_telegram_id=callback.from_user.id,
            tournament_id=callback_data.tournament_id,
        )
    except AdminAccessDeniedError:
        await callback.answer(texts.admin.ACCESS_DENIED, show_alert=True)
        return
    except ResultTournamentNotFoundError:
        await callback.answer(texts.admin.ADMIN_RESULTS_NOT_FOUND, show_alert=True)
        return

    await state.clear()
    await callback.answer()
    if callback.message is not None:
        await _delete_callback_message(callback)
        await callback.message.answer(
            format_admin_result_menu(draft),
            reply_markup=keyboards.admin_result_menu_keyboard(draft.tournament.id),
        )


@router.callback_query(keyboards.AdminResultMenuCallback.filter())
async def select_result_menu_action(
    callback: CallbackQuery,
    callback_data: keyboards.AdminResultMenuCallback,
    state: FSMContext,
) -> None:
    try:
        if callback_data.action == keyboards.AdminResultMenuAction.CANCEL:
            await state.clear()
            await callback.answer(texts.admin.ADMIN_RESULTS_CANCELLED)
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer(texts.admin.ADMIN_RESULTS_CANCELLED)
            return

        if callback_data.action == keyboards.AdminResultMenuAction.POOL:
            await state.set_state(AdminResultStates.entering_pool)
            await state.update_data(result_tournament_id=callback_data.tournament_id)
            await callback.answer()
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer(
                    texts.admin.ADMIN_RESULTS_POOL_PROMPT,
                    reply_markup=keyboards.admin_result_cancel_keyboard(
                        callback_data.tournament_id
                    ),
                )
            return

        if callback_data.action == keyboards.AdminResultMenuAction.PLAYERS:
            draft = await result_service.get_or_create_draft(
                admin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
            )
            page = pagination_service.paginate(
                draft.players,
                page=0,
                page_size=keyboards.ADMIN_RESULT_PAGE_SIZE,
            )
            await callback.answer()
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer(
                    format_admin_result_players(draft, page),
                    reply_markup=keyboards.admin_result_players_keyboard(draft, page),
                )
            return

        if callback_data.action == keyboards.AdminResultMenuAction.CHECK:
            errors = await result_service.validate_draft(
                admin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
            )
            await callback.answer()
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer(
                    texts.admin.admin_result_check_failed(errors)
                    if errors
                    else texts.admin.ADMIN_RESULTS_CHECK_OK
                )
            return

        draft = await result_service.close_tournament(
            admin_telegram_id=callback.from_user.id,
            tournament_id=callback_data.tournament_id,
        )
    except AdminAccessDeniedError:
        await callback.answer(texts.admin.ACCESS_DENIED, show_alert=True)
        return
    except ResultTournamentNotFoundError:
        await callback.answer(texts.admin.ADMIN_RESULTS_NOT_FOUND, show_alert=True)
        return
    except ResultValidationError as error:
        await callback.answer(
            texts.admin.ADMIN_RESULTS_CHECK_FAILED_SHORT,
            show_alert=True,
        )
        if callback.message is not None:
            await callback.message.answer(texts.admin.admin_result_check_failed(error.errors))
        return

    await state.clear()
    await callback.answer(texts.admin.ADMIN_RESULTS_CLOSED)
    if callback.message is not None:
        await _delete_callback_message(callback)
        await callback.message.answer(
            "\n".join(
                [
                    texts.admin.ADMIN_RESULTS_CLOSED,
                    "",
                    format_admin_result_menu(draft),
                ]
            )
        )


@router.callback_query(keyboards.AdminResultPlayerCallback.filter())
async def select_result_player(
    callback: CallbackQuery,
    callback_data: keyboards.AdminResultPlayerCallback,
    state: FSMContext,
) -> None:
    try:
        if callback_data.action == keyboards.AdminResultPlayerAction.CANCEL:
            await state.clear()
            await callback.answer(texts.admin.ADMIN_RESULTS_CANCELLED)
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer(texts.admin.ADMIN_RESULTS_CANCELLED)
            return

        draft = await result_service.get_or_create_draft(
            admin_telegram_id=callback.from_user.id,
            tournament_id=callback_data.tournament_id,
        )
        if callback_data.action == keyboards.AdminResultPlayerAction.BACK:
            await state.clear()
            await callback.answer()
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer(
                    format_admin_result_menu(draft),
                    reply_markup=keyboards.admin_result_menu_keyboard(
                        draft.tournament.id
                    ),
                )
            return

        page = pagination_service.paginate(
            draft.players,
            page=callback_data.page,
            page_size=keyboards.ADMIN_RESULT_PAGE_SIZE,
        )
        if callback_data.action == keyboards.AdminResultPlayerAction.PAGE:
            await callback.answer()
            if callback.message is not None:
                await callback.message.edit_text(
                    format_admin_result_players(draft, page),
                    reply_markup=keyboards.admin_result_players_keyboard(draft, page),
                )
            return

        player = next(
            (
                player
                for player in draft.players
                if player.player_id == callback_data.player_id
            ),
            None,
        )
        if player is None:
            await callback.answer(texts.admin.PLAYER_NOT_FOUND, show_alert=True)
            return
    except AdminAccessDeniedError:
        await callback.answer(texts.admin.ACCESS_DENIED, show_alert=True)
        return
    except ResultTournamentNotFoundError:
        await callback.answer(texts.admin.ADMIN_RESULTS_NOT_FOUND, show_alert=True)
        return

    await state.set_state(AdminResultStates.entering_player_result)
    await state.update_data(
        result_tournament_id=callback_data.tournament_id,
        result_player_id=callback_data.player_id,
        result_page=callback_data.page,
    )
    await callback.answer()
    if callback.message is not None:
        await _delete_callback_message(callback)
        await callback.message.answer(
            f"{player.display_name}\n\n{texts.admin.ADMIN_RESULTS_PLAYER_PROMPT}",
            reply_markup=keyboards.admin_result_cancel_keyboard(callback_data.tournament_id),
        )


@router.callback_query(keyboards.AdminCandidateCallback.filter())
async def select_admin_candidate(
    callback: CallbackQuery,
    callback_data: keyboards.AdminCandidateCallback,
) -> None:
    try:
        if callback_data.action == keyboards.AdminCandidateAction.CANCEL:
            await callback.answer(texts.admin.ADMIN_CALENDAR_CANCELLED)
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer(texts.admin.ADMIN_CALENDAR_CANCELLED)
            return

        players = await player_service.list_admin_candidates_for_superadmin(
            callback.from_user.id
        )
    except AdminAccessDeniedError:
        await callback.answer(texts.admin.INSUFFICIENT_RIGHTS, show_alert=True)
        return

    if callback_data.action == keyboards.AdminCandidateAction.PAGE:
        page = pagination_service.paginate(
            players,
            page=callback_data.page,
            page_size=keyboards.ADMIN_CANDIDATE_PAGE_SIZE,
        )
        await callback.answer()
        if callback.message is not None:
            await callback.message.edit_text(
                texts.admin.admin_candidate_list(page),
                reply_markup=keyboards.admin_candidate_list_keyboard(page),
            )
        return

    player = next(
        (candidate for candidate in players if candidate.id == callback_data.player_id),
        None,
    )
    if player is None:
        await callback.answer(texts.admin.PLAYER_NOT_FOUND, show_alert=True)
        return

    await callback.answer()
    if callback.message is not None:
        await _delete_callback_message(callback)
        await callback.message.answer(
            texts.admin.admin_add_confirmation(player.display_name),
            reply_markup=keyboards.admin_add_confirmation_keyboard(player.id),
        )


@router.callback_query(keyboards.AdminAddCallback.filter())
async def confirm_add_admin(
    callback: CallbackQuery,
    callback_data: keyboards.AdminAddCallback,
) -> None:
    if callback_data.action == keyboards.AdminAddAction.CANCEL:
        await callback.answer(texts.admin.ADMIN_CALENDAR_CANCELLED)
        if callback.message is not None:
            await _delete_callback_message(callback)
            await callback.message.answer(texts.admin.ADMIN_CALENDAR_CANCELLED)
        return

    try:
        player = await player_service.add_admin(
            superadmin_telegram_id=callback.from_user.id,
            player_id=callback_data.player_id,
        )
    except AdminAccessDeniedError:
        await callback.answer(texts.admin.INSUFFICIENT_RIGHTS, show_alert=True)
        return
    except PlayerNotFoundError:
        await callback.answer(texts.admin.PLAYER_NOT_FOUND, show_alert=True)
        return
    except PlayerRoleAlreadyAssignedError:
        await callback.answer(texts.admin.ADMIN_ALREADY_ASSIGNED, show_alert=True)
        return

    await callback.answer(texts.admin.ADMIN_ADDED)
    if callback.message is not None:
        await _delete_callback_message(callback)
        await callback.message.answer(texts.admin.ADMIN_ADDED)

    try:
        await callback.bot.send_message(
            chat_id=player.telegram_id,
            text=texts.admin.ADMIN_ADDED_FOR_PLAYER,
            reply_markup=keyboards.main_keyboard_after_role_update(player),
        )
    except (TelegramBadRequest, TelegramForbiddenError):
        pass


@router.callback_query(keyboards.RegistrationListCallback.filter())
async def review_registration_list(
    callback: CallbackQuery,
    callback_data: keyboards.RegistrationListCallback,
) -> None:
    try:
        if callback_data.action == keyboards.RegistrationListAction.CANCEL:
            await callback.answer(texts.admin.REGISTRATION_CANCELLED)
            if callback.message is not None:
                try:
                    await callback.message.delete()
                except TelegramBadRequest:
                    pass
            return

        if callback_data.action == keyboards.RegistrationListAction.OPEN:
            review = await player_service.get_registration_review_for_admin(
                admin_telegram_id=callback.from_user.id,
                pending_player_id=callback_data.player_id,
            )
            await callback.answer()
            if callback.message is not None:
                await callback.message.edit_text(
                    format_registration_review(review.player, review.matches),
                    reply_markup=keyboards.registration_review_keyboard(
                        review.player.id,
                        has_matches=bool(review.matches),
                    ),
                )
            return

        admin_panel = await player_service.get_admin_panel_for_admin(callback.from_user.id)
        reviews = admin_panel.reviews
        if not reviews:
            await callback.answer()
            if callback.message is not None:
                await callback.message.edit_text(
                    texts.admin.NO_PENDING_REGISTRATIONS,
                    reply_markup=None,
                )
            return

        page = pagination_service.paginate(
            reviews,
            page=callback_data.page,
            page_size=keyboards.REGISTRATION_LIST_PAGE_SIZE,
        )
        await callback.answer()
        if callback.message is not None:
            await callback.message.edit_text(
                texts.admin.registration_list(page),
                reply_markup=keyboards.registration_list_keyboard(page),
            )
    except AdminAccessDeniedError:
        await callback.answer(texts.admin.ACCESS_DENIED, show_alert=True)
        return
    except (PlayerNotFoundError, RegistrationAlreadyReviewedError):
        await callback.answer(
            texts.admin.REGISTRATION_ALREADY_REVIEWED,
            show_alert=True,
        )


@router.message(F.text == keyboards.ADMIN_PANEL_EXIT)
async def exit_admin_panel(message: Message) -> None:
    if message.from_user is None:
        return

    try:
        admin_panel = await player_service.get_admin_panel_for_admin(message.from_user.id)
    except AdminAccessDeniedError:
        await message.answer(texts.admin.ACCESS_DENIED)
        return

    await message.answer(
        texts.admin.ADMIN_PANEL_EXITED,
        reply_markup=keyboards.main_keyboard_for_player(admin_panel.admin),
    )


@router.message(F.text == keyboards.ADMIN_PANEL_CALENDAR)
async def open_admin_calendar(message: Message) -> None:
    if message.from_user is None:
        return

    try:
        await player_service.require_superadmin(message.from_user.id)
    except AdminAccessDeniedError:
        await message.answer(texts.admin.INSUFFICIENT_RIGHTS)
        return

    await message.answer(
        texts.admin.ADMIN_CALENDAR_PROMPT,
        reply_markup=keyboards.admin_calendar_keyboard(),
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
            if callback_data.action == keyboards.RegistrationReviewAction.APPROVE:
                matches = await player_service.get_registration_matches_for_admin(
                    admin_telegram_id=callback.from_user.id,
                    pending_player_id=callback_data.player_id,
                )
                if len(matches) > 1:
                    await callback.answer()
                    if callback.message is not None:
                        await callback.message.edit_reply_markup(
                            reply_markup=keyboards.registration_match_selection_keyboard(
                                callback_data.player_id,
                                matches,
                            )
                        )
                    return

            review_result = await player_service.approve_registration(
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
                review_result.player.display_name
            )
            player_keyboard = keyboards.main_keyboard_after_registration()
        elif callback_data.action == keyboards.RegistrationReviewAction.CANCEL:
            await callback.answer(texts.admin.REGISTRATION_CANCELLED)
            if callback.message is not None:
                try:
                    await callback.message.delete()
                except TelegramBadRequest:
                    pass
            return
        else:
            review_result = await player_service.reject_registration(
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

    await _send_registration_review_result(
        callback=callback,
        review_result=review_result,
        result_text=result_text,
        player_text=player_text,
        player_keyboard=player_keyboard,
    )


@router.callback_query(keyboards.RegistrationMatchSelectionCallback.filter())
async def select_registration_match(
    callback: CallbackQuery,
    callback_data: keyboards.RegistrationMatchSelectionCallback,
) -> None:
    try:
        review_result = await player_service.approve_registration(
            admin_telegram_id=callback.from_user.id,
            player_id=callback_data.player_id,
            historical_player_id=callback_data.historical_player_id,
        )
    except AdminAccessDeniedError:
        await callback.answer(texts.admin.ACCESS_DENIED, show_alert=True)
        return
    except PlayerNotFoundError:
        await callback.answer(texts.admin.PLAYER_NOT_FOUND, show_alert=True)
        return
    except (RegistrationAlreadyReviewedError, RegistrationMatchNotFoundError):
        await callback.answer(
            texts.admin.REGISTRATION_ALREADY_REVIEWED,
            show_alert=True,
        )
        return

    await _send_registration_review_result(
        callback=callback,
        review_result=review_result,
        result_text=texts.admin.REGISTRATION_APPROVED,
        player_text=texts.admin.registration_approved_message(
            review_result.player.display_name
        ),
        player_keyboard=keyboards.main_keyboard_after_registration(),
    )


async def _send_registration_review_result(
    callback: CallbackQuery,
    review_result: RegistrationReviewResultView,
    result_text: str,
    player_text: str,
    player_keyboard: object,
) -> None:
    await callback.answer(result_text)
    player = review_result.player
    admin_review_text = callback.message.text if callback.message is not None else ""
    reviewed_text = texts.admin.reviewed_by_admin(
        review_text=admin_review_text or format_registration_review(player),
        result_text=result_text,
        admin_name=callback.from_user.full_name,
    )
    if callback.message is not None:
        try:
            await callback.message.edit_text(reviewed_text)
        except TelegramBadRequest:
            pass

    for admin in review_result.admins:
        if admin.telegram_id == callback.from_user.id:
            continue
        try:
            await callback.bot.send_message(
                chat_id=admin.telegram_id,
                text=reviewed_text,
            )
        except (TelegramBadRequest, TelegramForbiddenError):
            continue

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
    state: FSMContext,
) -> None:
    action = CalendarPromptAction(callback_data.action.value)
    try:
        await player_service.require_superadmin(callback.from_user.id)
        if callback_data.action == keyboards.CalendarPromptAction.EDIT:
            await state.clear()
            prompt = await calendar_service.get_prompt(callback_data.prompt_id)
            if callback.message is not None:
                await _delete_callback_message(callback)
                if prompt.kind == "season_proposal":
                    await callback.message.answer(
                        texts.admin.ADMIN_CALENDAR_EDIT_MENU,
                        reply_markup=keyboards.season_edit_keyboard(callback_data.prompt_id),
                    )
                else:
                    await callback.message.answer(
                        texts.admin.ADMIN_CALENDAR_EDIT_MENU,
                        reply_markup=keyboards.tournament_day_edit_keyboard(prompt),
                    )
            await callback.answer()
            return

        await state.clear()
        resolved_prompt = await calendar_service.resolve_prompt(
            prompt_id=callback_data.prompt_id,
            admin_telegram_id=callback.from_user.id,
            action=action,
        )
    except AdminAccessDeniedError:
        await callback.answer(texts.admin.INSUFFICIENT_RIGHTS, show_alert=True)
        return
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
        result_text = (
            texts.admin.ADMIN_CALENDAR_SEASON_CREATED
            if resolved_prompt.kind == "season_proposal"
            else texts.admin.ADMIN_CALENDAR_TOURNAMENTS_CREATED
        )
        if resolved_prompt.kind == "season_proposal":
            await callback.answer(result_text)
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer(format_created_season_prompt(resolved_prompt))
            return
        await callback.answer(result_text)
        if callback.message is not None:
            await _delete_callback_message(callback)
            await callback.message.answer(format_created_tournaments_prompt(resolved_prompt))
        return
    elif callback_data.action == keyboards.CalendarPromptAction.CANCEL:
        result_text = texts.admin.CALENDAR_PROMPT_CANCELLED
        await state.clear()
        await callback.answer(result_text)
        if callback.message is not None:
            await _delete_callback_message(callback)
            await callback.message.answer(result_text)
        return
    else:
        result_text = texts.admin.CALENDAR_PROMPT_NEEDS_CHANGES

    await callback.answer(result_text)
    if callback.message is not None:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest:
            pass
        await callback.message.answer(
            texts.admin.calendar_reviewed_by_admin(
                prompt_text=callback.message.text or "",
                result_text=result_text,
                admin_name=callback.from_user.full_name,
            )
        )


@router.callback_query(keyboards.AdminCalendarCallback.filter())
async def select_admin_calendar_section(
    callback: CallbackQuery,
    callback_data: keyboards.AdminCalendarCallback,
) -> None:
    try:
        await player_service.require_superadmin(callback.from_user.id)
    except AdminAccessDeniedError:
        await callback.answer(texts.admin.INSUFFICIENT_RIGHTS, show_alert=True)
        return

    await _delete_callback_message(callback)

    if callback_data.action == keyboards.AdminCalendarAction.CANCEL:
        await callback.answer(texts.admin.ADMIN_CALENDAR_CANCELLED)
        if callback.message is not None:
            await callback.message.answer(texts.admin.ADMIN_CALENDAR_CANCELLED)
        return

    if callback_data.action == keyboards.AdminCalendarAction.SEASONS:
        try:
            prompt = await calendar_service.get_or_create_manual_season_prompt()
        except CalendarPromptEmptyError:
            await callback.answer(texts.admin.ADMIN_CALENDAR_EMPTY_SEASONS)
            if callback.message is not None:
                await callback.message.answer(texts.admin.ADMIN_CALENDAR_EMPTY_SEASONS)
            return

        await callback.answer()
        if callback.message is not None:
            await callback.message.answer(
                format_manual_season_prompt(prompt),
                reply_markup=keyboards.manual_season_prompt_keyboard(prompt.id),
            )
        return

    try:
        prompt = await calendar_service.get_or_create_manual_tournaments_prompt()
    except CalendarPromptEmptyError:
        await callback.answer(texts.admin.ADMIN_CALENDAR_EMPTY_TOURNAMENTS)
        if callback.message is not None:
            await callback.message.answer(texts.admin.ADMIN_CALENDAR_EMPTY_TOURNAMENTS)
        return

    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(
            format_admin_calendar_prompt(prompt),
            reply_markup=keyboards.manual_tournaments_prompt_keyboard(prompt.id),
        )


@router.callback_query(keyboards.TournamentDayEditCallback.filter())
async def select_tournament_edit_day(
    callback: CallbackQuery,
    callback_data: keyboards.TournamentDayEditCallback,
    state: FSMContext,
) -> None:
    try:
        await player_service.require_superadmin(callback.from_user.id)
    except AdminAccessDeniedError:
        await callback.answer(texts.admin.INSUFFICIENT_RIGHTS, show_alert=True)
        return

    await _delete_callback_message(callback)
    if callback_data.action == keyboards.TournamentDayEditAction.CANCEL:
        await state.clear()
        await callback.answer(texts.admin.ADMIN_CALENDAR_CANCELLED)
        if callback.message is not None:
            await callback.message.answer(texts.admin.ADMIN_CALENDAR_CANCELLED)
        return

    await state.clear()
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(
            texts.admin.ADMIN_CALENDAR_EDIT_MENU,
            reply_markup=keyboards.tournament_field_edit_keyboard(
                callback_data.prompt_id,
                callback_data.tournament_index,
            ),
        )


@router.callback_query(keyboards.TournamentEditCallback.filter())
async def select_tournament_edit_field(
    callback: CallbackQuery,
    callback_data: keyboards.TournamentEditCallback,
    state: FSMContext,
) -> None:
    try:
        await player_service.require_superadmin(callback.from_user.id)
    except AdminAccessDeniedError:
        await callback.answer(texts.admin.INSUFFICIENT_RIGHTS, show_alert=True)
        return

    await _delete_callback_message(callback)
    if callback_data.action == keyboards.TournamentEditAction.CANCEL:
        await state.clear()
        await callback.answer(texts.admin.ADMIN_CALENDAR_CANCELLED)
        if callback.message is not None:
            await callback.message.answer(texts.admin.ADMIN_CALENDAR_CANCELLED)
        return

    if callback_data.action == keyboards.TournamentEditAction.TYPE:
        tournament_types = await calendar_service.list_tournament_type_options()
        await callback.answer()
        if callback.message is not None:
            await callback.message.answer(
                texts.admin.ADMIN_CALENDAR_EDIT_MENU,
                reply_markup=keyboards.tournament_type_edit_keyboard(
                    callback_data.prompt_id,
                    callback_data.tournament_index,
                    tournament_types,
                ),
            )
        return

    state_name = (
        CalendarTournamentEditStates.entering_economy
        if callback_data.action == keyboards.TournamentEditAction.ECONOMY
        else CalendarTournamentEditStates.entering_rebuys
    )
    await state.set_state(state_name)
    await state.update_data(
        tournament_prompt_id=callback_data.prompt_id,
        tournament_index=callback_data.tournament_index,
    )
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(
            TOURNAMENT_ECONOMY_PROMPT
            if callback_data.action == keyboards.TournamentEditAction.ECONOMY
            else TOURNAMENT_REBUYS_PROMPT,
            reply_markup=keyboards.tournament_edit_cancel_keyboard(
                callback_data.prompt_id,
                callback_data.tournament_index,
            ),
        )


@router.callback_query(keyboards.TournamentTypeEditCallback.filter())
async def select_tournament_type(
    callback: CallbackQuery,
    callback_data: keyboards.TournamentTypeEditCallback,
    state: FSMContext,
) -> None:
    try:
        await player_service.require_superadmin(callback.from_user.id)
        prompt = await calendar_service.update_tournament_prompt_type(
            prompt_id=callback_data.prompt_id,
            tournament_index=callback_data.tournament_index,
            tournament_type_id=callback_data.tournament_type_id,
        )
    except AdminAccessDeniedError:
        await callback.answer(texts.admin.INSUFFICIENT_RIGHTS, show_alert=True)
        return
    except (CalendarPromptNotFoundError, CalendarPromptAlreadyResolvedError):
        await callback.answer(
            texts.admin.CALENDAR_PROMPT_ALREADY_RESOLVED,
            show_alert=True,
        )
        return
    except CalendarPromptInvalidPayloadError:
        await callback.answer(texts.admin.CALENDAR_PROMPT_NOT_FOUND, show_alert=True)
        return

    await state.clear()
    await callback.answer(texts.admin.CALENDAR_PROMPT_CONFIRMED)
    if callback.message is not None:
        await _delete_callback_message(callback)
        await callback.message.answer(
            format_admin_calendar_prompt(prompt),
            reply_markup=keyboards.manual_tournaments_prompt_keyboard(prompt.id),
        )


@router.message(AdminResultStates.entering_pool)
async def enter_result_pool(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return

    data = await state.get_data()
    tournament_id = int(data["result_tournament_id"])
    try:
        draft = await result_service.set_points_pool(
            admin_telegram_id=message.from_user.id,
            tournament_id=tournament_id,
            points_pool=parse_positive_decimal(message.text or ""),
        )
    except AdminAccessDeniedError:
        await state.clear()
        await message.answer(texts.admin.ACCESS_DENIED)
        return
    except ResultTournamentNotFoundError:
        await state.clear()
        await message.answer(texts.admin.ADMIN_RESULTS_NOT_FOUND)
        return
    except (InvalidOperation, ResultInvalidPoolError, ValueError):
        await message.answer(texts.admin.ADMIN_RESULTS_INVALID_POOL)
        return

    await state.clear()
    await message.answer(
        format_admin_result_menu(draft),
        reply_markup=keyboards.admin_result_menu_keyboard(draft.tournament.id),
    )


@router.message(AdminResultStates.entering_player_result)
async def enter_player_result(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return

    data = await state.get_data()
    tournament_id = int(data["result_tournament_id"])
    player_id = int(data["result_player_id"])
    page_number = int(data.get("result_page", 0))
    try:
        place, knockouts_count, boss_knockouts_count = parse_player_result(
            message.text or ""
        )
        draft = await result_service.update_player_result(
            admin_telegram_id=message.from_user.id,
            tournament_id=tournament_id,
            player_id=player_id,
            place=place,
            knockouts_count=knockouts_count,
            boss_knockouts_count=boss_knockouts_count,
        )
    except AdminAccessDeniedError:
        await state.clear()
        await message.answer(texts.admin.ACCESS_DENIED)
        return
    except ResultTournamentNotFoundError:
        await state.clear()
        await message.answer(texts.admin.ADMIN_RESULTS_NOT_FOUND)
        return
    except (ResultInvalidPlayerDataError, ResultPlayerNotFoundError, ValueError):
        await message.answer(texts.admin.ADMIN_RESULTS_INVALID_PLAYER_DATA)
        return

    await state.clear()
    page = pagination_service.paginate(
        draft.players,
        page=page_number,
        page_size=keyboards.ADMIN_RESULT_PAGE_SIZE,
    )
    await message.answer(texts.admin.ADMIN_RESULTS_SAVED)
    await message.answer(
        format_admin_result_players(draft, page),
        reply_markup=keyboards.admin_result_players_keyboard(draft, page),
    )


@router.callback_query(keyboards.SeasonEditCallback.filter())
async def select_season_edit_field(
    callback: CallbackQuery,
    callback_data: keyboards.SeasonEditCallback,
    state: FSMContext,
) -> None:
    try:
        await player_service.require_superadmin(callback.from_user.id)
    except AdminAccessDeniedError:
        await callback.answer(texts.admin.INSUFFICIENT_RIGHTS, show_alert=True)
        return

    await _delete_callback_message(callback)
    if callback_data.action == keyboards.SeasonEditAction.CANCEL:
        await state.clear()
        await callback.answer(texts.admin.ADMIN_CALENDAR_CANCELLED)
        if callback.message is not None:
            await callback.message.answer(texts.admin.ADMIN_CALENDAR_CANCELLED)
        return

    await state.set_state(CalendarSeasonEditStates.entering_value)
    await state.update_data(
        season_prompt_id=callback_data.prompt_id,
        season_edit_field=callback_data.action.value,
    )
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(SEASON_EDIT_PROMPTS[callback_data.action])


@router.message(CalendarTournamentEditStates.entering_economy)
async def enter_tournament_economy(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return

    try:
        await player_service.require_superadmin(message.from_user.id)
    except AdminAccessDeniedError:
        await state.clear()
        await message.answer(texts.admin.INSUFFICIENT_RIGHTS)
        return

    data = await state.get_data()
    try:
        entry_fee, entry_stack, addon_fee, addon_stack = parse_tournament_economy(
            message.text or ""
        )
        prompt = await calendar_service.update_tournament_prompt_economy(
            prompt_id=int(data["tournament_prompt_id"]),
            tournament_index=int(data["tournament_index"]),
            entry_fee=entry_fee,
            entry_stack=entry_stack,
            addon_fee=addon_fee,
            addon_stack=addon_stack,
        )
    except ValueError:
        await message.answer(TOURNAMENT_ECONOMY_PROMPT)
        return
    except (CalendarPromptNotFoundError, CalendarPromptAlreadyResolvedError):
        await state.clear()
        await message.answer(texts.admin.CALENDAR_PROMPT_ALREADY_RESOLVED)
        return

    await state.clear()
    await message.answer(
        format_admin_calendar_prompt(prompt),
        reply_markup=keyboards.manual_tournaments_prompt_keyboard(prompt.id),
    )


@router.message(CalendarTournamentEditStates.entering_rebuys)
async def enter_tournament_rebuys(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return

    try:
        await player_service.require_superadmin(message.from_user.id)
    except AdminAccessDeniedError:
        await state.clear()
        await message.answer(texts.admin.INSUFFICIENT_RIGHTS)
        return

    data = await state.get_data()
    try:
        prompt = await calendar_service.update_tournament_prompt_rebuys(
            prompt_id=int(data["tournament_prompt_id"]),
            tournament_index=int(data["tournament_index"]),
            rebuys=parse_tournament_rebuys(message.text or ""),
        )
    except ValueError:
        await message.answer(TOURNAMENT_REBUYS_PROMPT)
        return
    except (CalendarPromptNotFoundError, CalendarPromptAlreadyResolvedError):
        await state.clear()
        await message.answer(texts.admin.CALENDAR_PROMPT_ALREADY_RESOLVED)
        return

    await state.clear()
    await message.answer(
        format_admin_calendar_prompt(prompt),
        reply_markup=keyboards.manual_tournaments_prompt_keyboard(prompt.id),
    )


@router.message(CalendarSeasonEditStates.entering_value)
async def enter_season_edit_value(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return

    try:
        await player_service.require_superadmin(message.from_user.id)
    except AdminAccessDeniedError:
        await state.clear()
        await message.answer(texts.admin.INSUFFICIENT_RIGHTS)
        return

    data = await state.get_data()
    prompt_id = int(data["season_prompt_id"])
    field = keyboards.SeasonEditAction(data["season_edit_field"])
    value = " ".join((message.text or "").split())
    if not value:
        await message.answer(SEASON_EDIT_PROMPTS[field])
        return

    try:
        if field == keyboards.SeasonEditAction.NAME:
            prompt = await calendar_service.update_season_prompt(
                prompt_id=prompt_id,
                name=value,
            )
        elif field == keyboards.SeasonEditAction.STARTS_AT:
            prompt = await calendar_service.update_season_prompt(
                prompt_id=prompt_id,
                starts_at=parse_admin_date(value),
            )
        else:
            prompt = await calendar_service.update_season_prompt(
                prompt_id=prompt_id,
                ends_at=parse_admin_date(value),
            )
    except CalendarPromptInvalidPayloadError:
        await message.answer(
            texts.admin.invalid_calendar_period(SEASON_EDIT_PROMPTS[field])
        )
        return
    except ValueError:
        await message.answer(texts.admin.ADMIN_CALENDAR_INVALID_DATE)
        return
    except (CalendarPromptNotFoundError, CalendarPromptAlreadyResolvedError):
        await state.clear()
        await message.answer(texts.admin.CALENDAR_PROMPT_ALREADY_RESOLVED)
        return

    await state.clear()
    await message.answer(
        format_manual_season_prompt(prompt),
        reply_markup=keyboards.manual_season_prompt_keyboard(prompt.id),
    )


async def _delete_callback_message(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest:
            pass


def parse_admin_date(value: str) -> date:
    match = re.fullmatch(r"(\d{1,2})\.(\d{2})\.(\d{4})", value.strip())
    if match is None:
        raise ValueError
    day, month, year = (int(part) for part in match.groups())
    return date(year, month, day)


def parse_tournament_economy(value: str) -> tuple[int, int, int, int]:
    parts = [parse_positive_int(part) for part in re.split(r"\s*-\s*", value.strip())]
    if len(parts) != 4:
        raise ValueError
    entry_fee, entry_stack, addon_fee, addon_stack = parts
    if min(entry_fee, entry_stack, addon_fee, addon_stack) <= 0:
        raise ValueError
    return entry_fee, entry_stack, addon_fee, addon_stack


def parse_tournament_rebuys(value: str) -> list[dict[str, int]]:
    parts = re.split(r"\s*-\s*", value.strip())
    if len(parts) != 2:
        raise ValueError
    fees = [parse_positive_int(part) for part in re.split(r"\s*/\s*", parts[0])]
    stacks = [parse_positive_int(part) for part in re.split(r"\s*/\s*", parts[1])]
    if not fees or len(fees) != len(stacks):
        raise ValueError
    return [
        {
            "fee": fee,
            "stack": stack,
        }
        for fee, stack in zip(fees, stacks, strict=True)
    ]


def parse_positive_decimal(value: str) -> Decimal:
    normalized = re.sub(r"\s+", "", value).replace(",", ".")
    result = Decimal(normalized)
    if result <= 0:
        raise ValueError
    return result


def parse_player_result(value: str) -> tuple[int | None, int, int]:
    parts = [part.strip() for part in re.split(r"\s*-\s*", value.strip())]
    if len(parts) != 3:
        raise ValueError
    place = None if parts[0] in {"", "0", "—"} else parse_positive_int(parts[0])
    knockouts_count = parse_nonnegative_int(parts[1])
    boss_knockouts_count = parse_nonnegative_int(parts[2])
    return place, knockouts_count, boss_knockouts_count


def parse_nonnegative_int(value: str) -> int:
    normalized = re.sub(r"\s+", "", value)
    if not normalized.isdecimal():
        raise ValueError
    return int(normalized)


def parse_positive_int(value: str) -> int:
    normalized = re.sub(r"\s+", "", value)
    if not normalized.isdecimal():
        raise ValueError
    return int(normalized)
