import re
from datetime import date

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from app.bot.telegram import keyboards, texts
from app.bot.telegram.formatters import (
    format_admin_calendar_prompt,
    format_admin_result_field_prompt,
    format_admin_result_menu,
    format_admin_result_no_result_confirmation,
    format_admin_result_no_result_players,
    format_admin_result_player_detail,
    format_admin_result_players,
    format_admin_result_tournament_list,
    format_admin_tournament_registration_player_list,
    format_admin_tournament_registration_tournament_list,
    format_created_season,
    format_created_tournaments_prompt,
    format_public_weekly_schedule,
    format_season_proposal,
    format_tournament_check_in,
    format_tournament_check_in_finished,
    format_tournament_label,
)
from app.bot.telegram.notifications import format_registration_review
from app.bot.telegram.states import (
    AdminResultStates,
    AdminTournamentRegistrationStates,
    CalendarSeasonProposalEditStates,
)
from app.services.calendar_service import (
    CalendarDefaultTournamentTypeNotFoundError,
    CalendarPromptAction,
    CalendarPromptAlreadyResolvedError,
    CalendarPromptInvalidPayloadError,
    CalendarPromptNotFoundError,
    CalendarTournamentDateAlreadyExistsError,
    CalendarTournamentDateNotInPromptError,
    CalendarWeeklyPendingConflictError,
    CalendarWeeklyPromptEmptyError,
    CalendarWeeklyPromptIntegrityError,
    calendar_service,
)
from app.services.dto import (
    RegistrationReviewResultView,
)
from app.services.pagination import pagination_service
from app.services.result_service import (
    ResultField,
    ResultInvalidPlayerDataError,
    ResultService,
    ResultTournamentNotFoundError,
    ResultUserNotFoundError,
    ResultValidationError,
    result_service,
)
from app.services.season_service import (
    SeasonConflictError,
    SeasonDateOverlapError,
    SeasonNameAlreadyExistsError,
    SeasonNameInvalidError,
    SeasonProposalAlreadyResolvedError,
    SeasonProposalInvalidPayloadError,
    SeasonProposalNotFoundError,
    SeasonScheduledConflictError,
    SeasonScoringConfigAmbiguousError,
    SeasonScoringConfigNotFoundError,
    SeasonStartDateError,
    season_service,
)
from app.services.tournament_participant_service import (
    TournamentCheckInClosedError,
    TournamentCheckInHasResultError,
    TournamentCheckInNotFoundError,
    TournamentCheckInRegistrationNotFoundError,
    TournamentCheckInUserNotFoundError,
    tournament_participant_service,
)
from app.services.tournament_service import (
    TournamentUnavailableError,
    TournamentUserNotFoundError,
    tournament_service,
)
from app.services.user_service import (
    AdminAccessDeniedError,
    RegistrationAlreadyReviewedError,
    RegistrationCandidateNotFoundError,
    UserNotFoundError,
    UserRoleAlreadyAssignedError,
    user_service,
)

router = Router(name="admin")
RESULT_SUMMARY_PARSE_MODE = "Markdown"


@router.message(Command("admin"))
@router.message(F.text == keyboards.MAIN_ADMIN)
async def open_admin_panel(message: Message) -> None:
    if message.from_user is None:
        return

    try:
        admin_panel = await user_service.get_admin_panel_for_admin(message.from_user.id)
    except AdminAccessDeniedError:
        await message.answer(texts.admin.ACCESS_DENIED)
        return

    await message.answer(
        texts.admin.ADMIN_PANEL_WELCOME,
        reply_markup=keyboards.admin_panel_keyboard(admin_panel.admin),
    )


@router.message(F.text == keyboards.ADMIN_PANEL_SUPERADMIN)
async def open_superadmin_panel(message: Message) -> None:
    if message.from_user is None:
        return

    try:
        await user_service.require_superadmin(message.from_user.id)
    except AdminAccessDeniedError:
        await message.answer(texts.admin.INSUFFICIENT_RIGHTS)
        return

    await message.answer(
        texts.admin.SUPERADMIN_PANEL_WELCOME,
        reply_markup=keyboards.superadmin_panel_keyboard(),
    )


@router.message(F.text == keyboards.ADMIN_PANEL_BACK)
async def back_to_admin_panel(message: Message) -> None:
    if message.from_user is None:
        return

    try:
        admin_panel = await user_service.get_admin_panel_for_admin(message.from_user.id)
    except AdminAccessDeniedError:
        await message.answer(texts.admin.ACCESS_DENIED)
        return

    await message.answer(
        texts.admin.ADMIN_PANEL_WELCOME,
        reply_markup=keyboards.admin_panel_keyboard(admin_panel.admin),
    )


@router.message(F.text == keyboards.ADMIN_PANEL_REGISTRATIONS)
async def show_pending_registrations(message: Message) -> None:
    if message.from_user is None:
        return

    try:
        await user_service.require_superadmin(message.from_user.id)
        admin_panel = await user_service.get_admin_panel_for_admin(message.from_user.id)
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
        players = await user_service.list_admin_candidates_for_superadmin(message.from_user.id)
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
        tournaments = await result_service.list_open_tournaments_for_admin(message.from_user.id)
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


@router.message(F.text == keyboards.ADMIN_PANEL_REGISTER_PLAYER)
async def show_admin_registration_tournaments(message: Message) -> None:
    if message.from_user is None:
        return

    try:
        tournaments = await tournament_service.list_registration_tournaments_for_admin(
            message.from_user.id
        )
    except AdminAccessDeniedError:
        await message.answer(texts.admin.ACCESS_DENIED)
        return

    if not tournaments:
        await message.answer(texts.admin.ADMIN_TOURNAMENT_REGISTRATION_NO_TOURNAMENTS)
        return

    page = pagination_service.paginate(
        tournaments,
        page=0,
        page_size=keyboards.ADMIN_TOURNAMENT_REGISTRATION_PAGE_SIZE,
    )
    await message.answer(
        format_admin_tournament_registration_tournament_list(page),
        reply_markup=keyboards.admin_tournament_registration_tournament_keyboard(page),
    )


@router.callback_query(keyboards.AdminTournamentRegistrationTournamentCallback.filter())
async def select_admin_registration_tournament(
    callback: CallbackQuery,
    callback_data: keyboards.AdminTournamentRegistrationTournamentCallback,
) -> None:
    try:
        if callback_data.action == keyboards.AdminTournamentRegistrationTournamentAction.CANCEL:
            await callback.answer(texts.admin.ADMIN_TOURNAMENT_REGISTRATION_CANCELLED)
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer(texts.admin.ADMIN_TOURNAMENT_REGISTRATION_CANCELLED)
            return

        tournaments = await tournament_service.list_registration_tournaments_for_admin(
            callback.from_user.id
        )
    except AdminAccessDeniedError:
        await callback.answer(texts.admin.ACCESS_DENIED, show_alert=True)
        return

    if callback_data.action == keyboards.AdminTournamentRegistrationTournamentAction.PAGE:
        page = pagination_service.paginate(
            tournaments,
            page=callback_data.page,
            page_size=keyboards.ADMIN_TOURNAMENT_REGISTRATION_PAGE_SIZE,
        )
        await callback.answer()
        if callback.message is not None:
            await callback.message.edit_text(
                format_admin_tournament_registration_tournament_list(page),
                reply_markup=keyboards.admin_tournament_registration_tournament_keyboard(page),
            )
        return

    tournament = next(
        (tournament for tournament in tournaments if tournament.id == callback_data.tournament_id),
        None,
    )
    if tournament is None:
        await callback.answer(
            texts.admin.ADMIN_TOURNAMENT_REGISTRATION_NOT_FOUND,
            show_alert=True,
        )
        return

    try:
        players = await tournament_service.list_players_for_admin_registration(
            callback.from_user.id
        )
    except AdminAccessDeniedError:
        await callback.answer(texts.admin.ACCESS_DENIED, show_alert=True)
        return

    if not players:
        await callback.answer()
        if callback.message is not None:
            await _delete_callback_message(callback)
            await callback.message.answer(texts.admin.ADMIN_TOURNAMENT_REGISTRATION_NO_PLAYERS)
        return

    page = pagination_service.paginate(
        players,
        page=0,
        page_size=keyboards.ADMIN_TOURNAMENT_REGISTRATION_PAGE_SIZE,
    )
    await callback.answer()
    if callback.message is not None:
        await _delete_callback_message(callback)
        await callback.message.answer(
            format_admin_tournament_registration_player_list(tournament, page),
            reply_markup=keyboards.admin_tournament_registration_player_keyboard(
                tournament.id,
                page,
            ),
        )


@router.callback_query(keyboards.AdminTournamentRegistrationPlayerCallback.filter())
async def select_admin_registration_player(
    callback: CallbackQuery,
    callback_data: keyboards.AdminTournamentRegistrationPlayerCallback,
    state: FSMContext,
) -> None:
    try:
        if callback_data.action == keyboards.AdminTournamentRegistrationPlayerAction.CANCEL:
            await state.clear()
            await callback.answer(texts.admin.ADMIN_TOURNAMENT_REGISTRATION_CANCELLED)
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer(texts.admin.ADMIN_TOURNAMENT_REGISTRATION_CANCELLED)
            return

        if callback_data.action == keyboards.AdminTournamentRegistrationPlayerAction.BACK:
            await state.clear()
            tournaments = await tournament_service.list_registration_tournaments_for_admin(
                callback.from_user.id
            )
            page = pagination_service.paginate(
                tournaments,
                page=0,
                page_size=keyboards.ADMIN_TOURNAMENT_REGISTRATION_PAGE_SIZE,
            )
            await callback.answer()
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer(
                    format_admin_tournament_registration_tournament_list(page),
                    reply_markup=keyboards.admin_tournament_registration_tournament_keyboard(page),
                )
            return

        tournaments = await tournament_service.list_registration_tournaments_for_admin(
            callback.from_user.id
        )
        tournament = next(
            (
                tournament
                for tournament in tournaments
                if tournament.id == callback_data.tournament_id
            ),
            None,
        )
        if tournament is None:
            await callback.answer(
                texts.admin.ADMIN_TOURNAMENT_REGISTRATION_NOT_FOUND,
                show_alert=True,
            )
            return

        players = await tournament_service.list_players_for_admin_registration(
            callback.from_user.id
        )
        if callback_data.action == keyboards.AdminTournamentRegistrationPlayerAction.SEARCH:
            await state.set_state(AdminTournamentRegistrationStates.entering_player_search)
            await state.update_data(admin_registration_tournament_id=callback_data.tournament_id)
            await callback.answer()
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer(
                    texts.admin.ADMIN_TOURNAMENT_REGISTRATION_SEARCH_PROMPT,
                    reply_markup=keyboards.admin_tournament_registration_search_cancel_keyboard(
                        callback_data.tournament_id
                    ),
                )
            return
        if callback_data.action == keyboards.AdminTournamentRegistrationPlayerAction.PAGE:
            page = pagination_service.paginate(
                players,
                page=callback_data.page,
                page_size=keyboards.ADMIN_TOURNAMENT_REGISTRATION_PAGE_SIZE,
            )
            await callback.answer()
            if callback.message is not None:
                await callback.message.edit_text(
                    format_admin_tournament_registration_player_list(tournament, page),
                    reply_markup=keyboards.admin_tournament_registration_player_keyboard(
                        tournament.id,
                        page,
                    ),
                )
            return

        tournament, player = await tournament_service.register_player_for_tournament_by_admin(
            admin_telegram_id=callback.from_user.id,
            tournament_id=callback_data.tournament_id,
            player_id=callback_data.player_id,
        )
    except AdminAccessDeniedError:
        await state.clear()
        await callback.answer(texts.admin.ACCESS_DENIED, show_alert=True)
        return
    except (TournamentUnavailableError, TournamentUserNotFoundError):
        await state.clear()
        await callback.answer(
            texts.admin.ADMIN_TOURNAMENT_REGISTRATION_NOT_FOUND,
            show_alert=True,
        )
        return

    await callback.answer(texts.user.ACTION_DONE)
    await state.clear()
    tournament_label = format_tournament_label(tournament)
    if callback.message is not None:
        await _delete_callback_message(callback)
        await callback.message.answer(
            texts.admin.admin_tournament_registration_success(
                player=player.display_name,
                tournament=tournament_label,
            )
        )

    try:
        await callback.bot.send_message(
            chat_id=player.telegram_id,
            text=texts.admin.admin_tournament_registration_player_notification(tournament_label),
            reply_markup=keyboards.main_keyboard_for_player(player),
        )
    except (TelegramBadRequest, TelegramForbiddenError):
        pass


@router.callback_query(keyboards.AdminResultTournamentCallback.filter())
async def select_result_tournament(
    callback: CallbackQuery,
    callback_data: keyboards.AdminResultTournamentCallback,
    state: FSMContext,
) -> None:
    callback_answered = False
    try:
        if callback_data.action == keyboards.AdminResultTournamentAction.CANCEL:
            await state.clear()
            await callback.answer(texts.admin.ADMIN_RESULTS_CANCELLED)
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer(texts.admin.ADMIN_RESULTS_CANCELLED)
            return

        if callback_data.action == keyboards.AdminResultTournamentAction.PAGE:
            await callback.answer()
            callback_answered = True
            tournaments = await result_service.list_open_tournaments_for_admin(
                callback.from_user.id
            )
            page = pagination_service.paginate(
                tournaments,
                page=callback_data.page,
                page_size=keyboards.ADMIN_RESULT_PAGE_SIZE,
            )
            if callback.message is not None:
                await callback.message.edit_text(
                    format_admin_result_tournament_list(page),
                    reply_markup=keyboards.admin_result_tournament_list_keyboard(page),
                )
            return

        await callback.answer()
        callback_answered = True
        draft = await result_service.get_or_create_draft(
            admin_telegram_id=callback.from_user.id,
            tournament_id=callback_data.tournament_id,
        )
    except AdminAccessDeniedError:
        if callback_answered and callback.message is not None:
            await callback.message.answer(texts.admin.ACCESS_DENIED)
        else:
            await callback.answer(texts.admin.ACCESS_DENIED, show_alert=True)
        return
    except ResultTournamentNotFoundError:
        if callback_answered and callback.message is not None:
            await callback.message.answer(texts.admin.ADMIN_RESULTS_NOT_FOUND)
        else:
            await callback.answer(texts.admin.ADMIN_RESULTS_NOT_FOUND, show_alert=True)
        return

    await state.clear()
    if callback.message is not None:
        await _delete_callback_message(callback)
        await callback.message.answer(
            format_admin_result_menu(draft),
            reply_markup=keyboards.admin_result_menu_keyboard(draft.tournament.id),
            parse_mode=RESULT_SUMMARY_PARSE_MODE,
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

        if callback_data.action == keyboards.AdminResultMenuAction.PARTICIPANTS:
            view = await tournament_participant_service.get_check_in(
                admin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
            )
            page = pagination_service.paginate(
                view.players,
                page=0,
                page_size=keyboards.ADMIN_RESULT_PAGE_SIZE,
            )
            await callback.answer()
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer(
                    format_tournament_check_in(view),
                    reply_markup=keyboards.admin_check_in_keyboard(view, page),
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
                    parse_mode=RESULT_SUMMARY_PARSE_MODE,
                )
            return

        await callback.answer(texts.admin.INSUFFICIENT_RIGHTS, show_alert=True)
        return
    except AdminAccessDeniedError:
        await callback.answer(texts.admin.ACCESS_DENIED, show_alert=True)
        return
    except (
        ResultTournamentNotFoundError,
        TournamentCheckInNotFoundError,
        TournamentCheckInClosedError,
    ):
        await callback.answer(texts.admin.ADMIN_RESULTS_NOT_FOUND, show_alert=True)
        return


@router.callback_query(keyboards.AdminCheckInCallback.filter())
async def select_check_in_action(
    callback: CallbackQuery,
    callback_data: keyboards.AdminCheckInCallback,
    state: FSMContext,
) -> None:
    try:
        if callback_data.action == keyboards.AdminCheckInAction.CANCEL:
            await state.clear()
            await callback.answer(texts.admin.ADMIN_RESULTS_CANCELLED)
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer(texts.admin.ADMIN_RESULTS_CANCELLED)
            return

        if callback_data.action == keyboards.AdminCheckInAction.BACK:
            await state.clear()
            view = await tournament_participant_service.get_check_in(
                admin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
            )
            page = pagination_service.paginate(
                view.players,
                page=callback_data.page,
                page_size=keyboards.ADMIN_RESULT_PAGE_SIZE,
            )
            await callback.answer()
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer(
                    format_tournament_check_in(view),
                    reply_markup=keyboards.admin_check_in_keyboard(view, page),
                )
            return

        if callback_data.action == keyboards.AdminCheckInAction.FINISH:
            await state.clear()
            view = await tournament_participant_service.get_check_in(
                admin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
            )
            draft = await result_service.get_or_create_draft(
                admin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
            )
            await callback.answer("Состав сохранён")
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer(format_tournament_check_in_finished(view))
                await callback.message.answer(
                    format_admin_result_menu(draft),
                    reply_markup=keyboards.admin_result_menu_keyboard(draft.tournament.id),
                    parse_mode=RESULT_SUMMARY_PARSE_MODE,
                )
            return

        if callback_data.action == keyboards.AdminCheckInAction.REGISTERED_SEARCH:
            await state.set_state(AdminResultStates.entering_registered_check_in_search)
            await state.update_data(check_in_tournament_id=callback_data.tournament_id)
            await callback.answer()
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer(
                    "Введи имя зарегистрированного игрока.",
                    reply_markup=keyboards.admin_result_cancel_keyboard(
                        callback_data.tournament_id
                    ),
                )
            return

        if callback_data.action == keyboards.AdminCheckInAction.DATABASE_SEARCH:
            await state.set_state(AdminResultStates.entering_database_check_in_search)
            await state.update_data(check_in_tournament_id=callback_data.tournament_id)
            await callback.answer()
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer(
                    "Введи имя игрока из базы.",
                    reply_markup=keyboards.admin_result_cancel_keyboard(
                        callback_data.tournament_id
                    ),
                )
            return

        if callback_data.action == keyboards.AdminCheckInAction.NEW_PLAYER:
            await state.set_state(AdminResultStates.entering_new_check_in_player)
            await state.update_data(check_in_tournament_id=callback_data.tournament_id)
            await callback.answer()
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer(
                    "Введи имя нового игрока.",
                    reply_markup=keyboards.admin_result_cancel_keyboard(
                        callback_data.tournament_id
                    ),
                )
            return

        if callback_data.action == keyboards.AdminCheckInAction.TOGGLE_REGISTERED:
            view = await tournament_participant_service.toggle_registered(
                admin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
                user_id=callback_data.player_id,
            )
        else:
            view = await tournament_participant_service.check_in_existing_user(
                admin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
                user_id=callback_data.player_id,
            )
    except AdminAccessDeniedError:
        await state.clear()
        await callback.answer(texts.admin.ACCESS_DENIED, show_alert=True)
        return
    except (
        TournamentCheckInNotFoundError,
        TournamentCheckInClosedError,
        TournamentCheckInRegistrationNotFoundError,
        TournamentCheckInUserNotFoundError,
    ):
        await callback.answer(texts.admin.ADMIN_RESULTS_NOT_FOUND, show_alert=True)
        return
    except TournamentCheckInHasResultError:
        message = (
            "Нельзя снять участника: для него уже внесены результаты.\n"
            "Сначала очистите место, нокауты и бонусные очки."
        )
        await callback.answer(message, show_alert=True)
        if callback.message is not None:
            await callback.message.answer(message)
        return

    await state.clear()
    page = pagination_service.paginate(
        view.players,
        page=callback_data.page,
        page_size=keyboards.ADMIN_RESULT_PAGE_SIZE,
    )
    await callback.answer(texts.admin.ADMIN_RESULTS_SAVED)
    if callback.message is not None:
        await callback.message.edit_text(
            format_tournament_check_in(view),
            reply_markup=keyboards.admin_check_in_keyboard(view, page),
        )


@router.callback_query(keyboards.AdminResultCloseCallback.filter())
async def confirm_result_close(
    callback: CallbackQuery,
    callback_data: keyboards.AdminResultCloseCallback,
    state: FSMContext,
) -> None:
    try:
        if callback_data.action == keyboards.AdminResultCloseAction.CANCEL:
            await state.clear()
            draft = await result_service.get_or_create_draft(
                admin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
            )
            await callback.answer(texts.admin.ADMIN_RESULTS_CANCELLED)
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer(
                    format_admin_result_menu(draft),
                    reply_markup=keyboards.admin_result_menu_keyboard(draft.tournament.id),
                    parse_mode=RESULT_SUMMARY_PARSE_MODE,
                )
            return

        errors = await result_service.validate_draft(
            admin_telegram_id=callback.from_user.id,
            tournament_id=callback_data.tournament_id,
        )
        if errors:
            await callback.answer()
            if callback.message is not None:
                await callback.message.answer(texts.admin.admin_result_check_failed(errors))
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
        await callback.answer()
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
            ),
            parse_mode=RESULT_SUMMARY_PARSE_MODE,
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
        if callback_data.action == keyboards.AdminResultPlayerAction.FINISH:
            await result_service.submit_results_by_admin(
                admin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
            )
            admin_panel = await user_service.get_admin_panel_for_admin(callback.from_user.id)
            await state.clear()
            await callback.answer(texts.admin.ADMIN_RESULTS_SAVED)
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer(
                    texts.admin.ADMIN_RESULTS_SUBMITTED,
                    reply_markup=keyboards.admin_panel_keyboard(admin_panel.admin),
                )
            return
        if callback_data.action == keyboards.AdminResultPlayerAction.NO_RESULT_LIST:
            await state.clear()
            await callback.answer()
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer(
                    format_admin_result_no_result_players(draft),
                    reply_markup=keyboards.admin_result_no_result_players_keyboard(draft),
                )
            return
        if callback_data.action == keyboards.AdminResultPlayerAction.RESTORE_RESULT:
            restored = await tournament_participant_service.restore_result_active(
                admin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
                user_id=callback_data.player_id,
            )
            draft = await result_service.get_or_create_draft(
                admin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
            )
            page = pagination_service.paginate(
                draft.players,
                page=callback_data.page,
                page_size=keyboards.ADMIN_RESULT_PAGE_SIZE,
            )
            await state.clear()
            await callback.answer(f"{restored.display_name} возвращён в список результатов")
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer(
                    format_admin_result_players(draft, page),
                    reply_markup=keyboards.admin_result_players_keyboard(draft, page),
                    parse_mode=RESULT_SUMMARY_PARSE_MODE,
                )
            return
        if callback_data.action == keyboards.AdminResultPlayerAction.BACK:
            await state.clear()
            await callback.answer()
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer(
                    format_admin_result_menu(draft),
                    reply_markup=keyboards.admin_result_menu_keyboard(draft.tournament.id),
                    parse_mode=RESULT_SUMMARY_PARSE_MODE,
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
                    parse_mode=RESULT_SUMMARY_PARSE_MODE,
                )
            return
        if callback_data.action == keyboards.AdminResultPlayerAction.CONFIRM_NO_RESULT:
            hidden = await tournament_participant_service.mark_no_result(
                admin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
                user_id=callback_data.player_id,
            )
            draft = await result_service.get_or_create_draft(
                admin_telegram_id=callback.from_user.id,
                tournament_id=callback_data.tournament_id,
            )
            page = pagination_service.paginate(
                draft.players,
                page=callback_data.page,
                page_size=keyboards.ADMIN_RESULT_PAGE_SIZE,
            )
            await state.clear()
            await callback.answer(f"{hidden.display_name} отмечен без результата")
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer(
                    format_admin_result_players(draft, page),
                    reply_markup=keyboards.admin_result_players_keyboard(draft, page),
                    parse_mode=RESULT_SUMMARY_PARSE_MODE,
                )
            return

        player = ResultService.find_result_player(draft, callback_data.player_id)
        if player is None:
            await callback.answer(texts.admin.PLAYER_NOT_FOUND, show_alert=True)
            return
        if callback_data.action == keyboards.AdminResultPlayerAction.NO_RESULT:
            await state.clear()
            await callback.answer()
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer(
                    format_admin_result_no_result_confirmation(player),
                    reply_markup=keyboards.admin_result_no_result_confirmation_keyboard(
                        tournament_id=callback_data.tournament_id,
                        page=callback_data.page,
                        player_id=callback_data.player_id,
                    ),
                )
            return
    except AdminAccessDeniedError:
        await callback.answer(texts.admin.ACCESS_DENIED, show_alert=True)
        return
    except (ResultTournamentNotFoundError, TournamentCheckInClosedError):
        await callback.answer(texts.admin.ADMIN_RESULTS_NOT_FOUND, show_alert=True)
        return
    except (TournamentCheckInUserNotFoundError, TournamentCheckInNotFoundError):
        await callback.answer(texts.admin.PLAYER_NOT_FOUND, show_alert=True)
        return
    except TournamentCheckInHasResultError:
        await callback.answer(
            "Нельзя отметить игрока «без результата»: по нему уже внесены данные.",
            show_alert=True,
        )
        if callback.message is not None:
            await callback.message.answer(
                "Нельзя отметить игрока «без результата»: по нему уже внесены данные.\n\n"
                "Сначала очистите место, нокауты и бонусные очки."
            )
        return
    except ResultValidationError as error:
        await callback.answer()
        if callback.message is not None:
            await callback.message.answer(texts.admin.admin_result_check_failed(error.errors))
        return

    await state.clear()
    await callback.answer()
    if callback.message is not None:
        await _delete_callback_message(callback)
        await callback.message.answer(
            format_admin_result_player_detail(draft, player),
            reply_markup=keyboards.admin_result_player_fields_keyboard(
                draft,
                player,
                callback_data.page,
            ),
        )


@router.callback_query(keyboards.AdminResultFieldCallback.filter())
async def select_result_field(
    callback: CallbackQuery,
    callback_data: keyboards.AdminResultFieldCallback,
    state: FSMContext,
) -> None:
    try:
        draft = await result_service.get_or_create_draft(
            admin_telegram_id=callback.from_user.id,
            tournament_id=callback_data.tournament_id,
        )
        player = ResultService.find_result_player(draft, callback_data.player_id)
        if player is None:
            await callback.answer(texts.admin.PLAYER_NOT_FOUND, show_alert=True)
            return

        if callback_data.action == keyboards.AdminResultFieldAction.CANCEL:
            await state.clear()
            await callback.answer(texts.admin.ADMIN_RESULTS_CANCELLED)
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer(texts.admin.ADMIN_RESULTS_CANCELLED)
            return

        if callback_data.action == keyboards.AdminResultFieldAction.DONE:
            await state.clear()
            page = pagination_service.paginate(
                draft.players,
                page=callback_data.page,
                page_size=keyboards.ADMIN_RESULT_PAGE_SIZE,
            )
            await callback.answer()
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer(
                    format_admin_result_players(draft, page),
                    reply_markup=keyboards.admin_result_players_keyboard(draft, page),
                    parse_mode=RESULT_SUMMARY_PARSE_MODE,
                )
            return

        service_field = to_result_field(callback_data.field)
        if service_field == ResultField.BONUS and not draft.supports_bonus_points:
            await callback.answer(texts.admin.ADMIN_RESULTS_NOT_FOUND, show_alert=True)
            return
        if service_field != ResultField.BONUS and not ResultService.result_field_is_allowed(
            draft.knockout_mode,
            service_field,
        ):
            await callback.answer(texts.admin.ADMIN_RESULTS_NOT_FOUND, show_alert=True)
            return

        await state.clear()
        await callback.answer()
        if callback.message is not None:
            await callback.message.edit_text(
                format_admin_result_field_prompt(
                    player,
                    result_field_name(callback_data.field),
                ),
                reply_markup=keyboards.admin_result_value_keyboard(
                    tournament_id=callback_data.tournament_id,
                    page=callback_data.page,
                    player_id=callback_data.player_id,
                    field=callback_data.field,
                    occupied_places=ResultService.occupied_result_places(draft),
                ),
            )
    except AdminAccessDeniedError:
        await callback.answer(texts.admin.ACCESS_DENIED, show_alert=True)
    except ResultTournamentNotFoundError:
        await callback.answer(texts.admin.ADMIN_RESULTS_NOT_FOUND, show_alert=True)


@router.callback_query(keyboards.AdminResultValueCallback.filter())
async def select_result_value(
    callback: CallbackQuery,
    callback_data: keyboards.AdminResultValueCallback,
    state: FSMContext,
) -> None:
    try:
        draft = await result_service.get_or_create_draft(
            admin_telegram_id=callback.from_user.id,
            tournament_id=callback_data.tournament_id,
        )
        player = ResultService.find_result_player(draft, callback_data.player_id)
        if player is None:
            await callback.answer(texts.admin.PLAYER_NOT_FOUND, show_alert=True)
            return

        if callback_data.action == keyboards.AdminResultValueAction.CANCEL:
            await state.clear()
            await callback.answer(texts.admin.ADMIN_RESULTS_CANCELLED)
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer(texts.admin.ADMIN_RESULTS_CANCELLED)
            return

        if callback_data.action == keyboards.AdminResultValueAction.BACK:
            await state.clear()
            await callback.answer()
            if callback.message is not None:
                await callback.message.edit_text(
                    format_admin_result_player_detail(draft, player),
                    reply_markup=keyboards.admin_result_player_fields_keyboard(
                        draft,
                        player,
                        callback_data.page,
                    ),
                )
            return

        service_field = to_result_field(callback_data.field)
        if service_field == ResultField.BONUS and not draft.supports_bonus_points:
            await callback.answer(texts.admin.ADMIN_RESULTS_NOT_FOUND, show_alert=True)
            return
        if service_field != ResultField.BONUS and not ResultService.result_field_is_allowed(
            draft.knockout_mode,
            service_field,
        ):
            await callback.answer(texts.admin.ADMIN_RESULTS_NOT_FOUND, show_alert=True)
            return

        if callback_data.action == keyboards.AdminResultValueAction.MANUAL:
            await state.set_state(AdminResultStates.entering_manual_value)
            await state.update_data(
                result_tournament_id=callback_data.tournament_id,
                result_player_id=callback_data.player_id,
                result_page=callback_data.page,
                result_field=callback_data.field.value,
                result_prompt_message_id=callback.message.message_id
                if callback.message is not None
                else 0,
            )
            await callback.answer()
            if callback.message is not None:
                await callback.message.edit_text(
                    texts.admin.ADMIN_RESULTS_MANUAL_VALUE_PROMPTS[callback_data.field.value],
                    reply_markup=keyboards.admin_result_manual_value_keyboard(
                        tournament_id=callback_data.tournament_id,
                        page=callback_data.page,
                        player_id=callback_data.player_id,
                        field=callback_data.field,
                    ),
                )
            return

        draft = await result_service.update_player_result_field(
            admin_telegram_id=callback.from_user.id,
            tournament_id=callback_data.tournament_id,
            player_id=callback_data.player_id,
            field=service_field,
            value=callback_data.value,
        )
        player = ResultService.find_result_player(draft, callback_data.player_id)
        if player is None:
            await callback.answer(texts.admin.PLAYER_NOT_FOUND, show_alert=True)
            return
        await state.clear()
        await callback.answer(texts.admin.ADMIN_RESULTS_SAVED)
        if callback.message is not None:
            if draft.knockout_mode == "none" and not draft.supports_bonus_points:
                page = pagination_service.paginate(
                    draft.players,
                    page=callback_data.page,
                    page_size=keyboards.ADMIN_RESULT_PAGE_SIZE,
                )
                await callback.message.edit_text(
                    format_admin_result_players(draft, page),
                    reply_markup=keyboards.admin_result_players_keyboard(draft, page),
                    parse_mode=RESULT_SUMMARY_PARSE_MODE,
                )
            else:
                await callback.message.edit_text(
                    format_admin_result_player_detail(draft, player),
                    reply_markup=keyboards.admin_result_player_fields_keyboard(
                        draft,
                        player,
                        callback_data.page,
                    ),
                )
    except AdminAccessDeniedError:
        await callback.answer(texts.admin.ACCESS_DENIED, show_alert=True)
    except ResultTournamentNotFoundError:
        await callback.answer(texts.admin.ADMIN_RESULTS_NOT_FOUND, show_alert=True)
    except (ResultInvalidPlayerDataError, ResultUserNotFoundError, ValueError):
        await callback.answer(
            texts.admin.ADMIN_RESULTS_INVALID_MANUAL_VALUE[callback_data.field.value],
            show_alert=True,
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

        players = await user_service.list_admin_candidates_for_superadmin(callback.from_user.id)
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
        player = await user_service.add_admin(
            superadmin_telegram_id=callback.from_user.id,
            player_id=callback_data.player_id,
        )
    except AdminAccessDeniedError:
        await callback.answer(texts.admin.INSUFFICIENT_RIGHTS, show_alert=True)
        return
    except UserNotFoundError:
        await callback.answer(texts.admin.PLAYER_NOT_FOUND, show_alert=True)
        return
    except UserRoleAlreadyAssignedError:
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
            review = await user_service.get_registration_review_for_admin(
                admin_telegram_id=callback.from_user.id,
                request_id=callback_data.request_id,
            )
            await callback.answer()
            if callback.message is not None:
                await callback.message.edit_text(
                    format_registration_review(review),
                    reply_markup=keyboards.registration_review_keyboard(
                        review.request.id,
                        can_edit_name=review.request.request_type == "new_player",
                        can_select_candidate=review.request.request_type == "link_existing_player",
                    ),
                )
            return

        await user_service.require_superadmin(callback.from_user.id)
        admin_panel = await user_service.get_admin_panel_for_admin(callback.from_user.id)
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
    except (UserNotFoundError, RegistrationAlreadyReviewedError):
        await callback.answer(
            texts.admin.REGISTRATION_ALREADY_REVIEWED,
            show_alert=True,
        )


@router.message(F.text == keyboards.ADMIN_PANEL_EXIT)
async def exit_admin_panel(message: Message) -> None:
    if message.from_user is None:
        return

    try:
        admin_panel = await user_service.get_admin_panel_for_admin(message.from_user.id)
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
        await user_service.require_superadmin(message.from_user.id)
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
        if callback_data.action == keyboards.RegistrationReviewAction.SELECT_CANDIDATE:
            review = await user_service.get_registration_review_for_admin(
                admin_telegram_id=callback.from_user.id,
                request_id=callback_data.request_id,
            )
            await callback.answer()
            if callback.message is not None:
                await callback.message.edit_reply_markup(
                    reply_markup=keyboards.registration_candidate_selection_keyboard(
                        callback_data.request_id,
                        review.candidates,
                    )
                )
            return

        if callback_data.action == keyboards.RegistrationReviewAction.EDIT_NAME:
            await callback.answer("Редактирование имени добавим следующим шагом.", show_alert=True)
            return

        if callback_data.action == keyboards.RegistrationReviewAction.APPROVE:
            review_result = await user_service.approve_registration(
                superadmin_telegram_id=callback.from_user.id,
                request_id=callback_data.request_id,
            )
            result_text = texts.admin.REGISTRATION_APPROVED
            player_text = "Ваша заявка одобрена."
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
            review_result = await user_service.reject_registration(
                superadmin_telegram_id=callback.from_user.id,
                request_id=callback_data.request_id,
            )
            result_text = texts.admin.REGISTRATION_REJECTED
            player_text = "Ваша заявка отклонена."
            player_keyboard = ReplyKeyboardRemove()
    except AdminAccessDeniedError:
        await callback.answer(texts.admin.ACCESS_DENIED, show_alert=True)
        return
    except UserNotFoundError:
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


@router.callback_query(keyboards.RegistrationCandidateSelectionCallback.filter())
async def select_registration_candidate(
    callback: CallbackQuery,
    callback_data: keyboards.RegistrationCandidateSelectionCallback,
) -> None:
    try:
        review = await user_service.select_registration_candidate(
            superadmin_telegram_id=callback.from_user.id,
            request_id=callback_data.request_id,
            user_id=callback_data.user_id,
        )
    except AdminAccessDeniedError:
        await callback.answer(texts.admin.ACCESS_DENIED, show_alert=True)
        return
    except UserNotFoundError:
        await callback.answer(texts.admin.PLAYER_NOT_FOUND, show_alert=True)
        return
    except (RegistrationAlreadyReviewedError, RegistrationCandidateNotFoundError):
        await callback.answer(
            texts.admin.REGISTRATION_ALREADY_REVIEWED,
            show_alert=True,
        )
        return

    await callback.answer("Игрок выбран.")
    if callback.message is not None:
        await callback.message.edit_text(
            format_registration_review(review),
            reply_markup=keyboards.registration_review_keyboard(
                review.request.id,
                can_select_candidate=True,
            ),
        )


async def _send_registration_review_result(
    callback: CallbackQuery,
    review_result: RegistrationReviewResultView,
    result_text: str,
    player_text: str,
    player_keyboard: object,
) -> None:
    await callback.answer(result_text)
    admin_review_text = callback.message.text if callback.message is not None else ""
    reviewed_text = texts.admin.reviewed_by_admin(
        review_text=admin_review_text,
        result_text=result_text,
        admin_name=callback.from_user.full_name,
    )
    if callback.message is not None:
        try:
            await callback.message.edit_text(reviewed_text)
        except TelegramBadRequest:
            pass

    for admin in review_result.admins:
        if admin.telegram_id is None or admin.telegram_id == callback.from_user.id:
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
            chat_id=review_result.request.telegram_id,
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
    try:
        await user_service.require_superadmin(callback.from_user.id)
        if callback_data.action == keyboards.CalendarPromptAction.EDIT:
            await state.clear()
            prompt = await calendar_service.get_tournament_prompt(callback_data.prompt_id)
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer(
                    texts.admin.ADMIN_CALENDAR_EDIT_MENU,
                    reply_markup=keyboards.tournament_prompt_day_edit_keyboard(prompt),
                )
            await callback.answer()
            return

        if callback_data.action == keyboards.CalendarPromptAction.BACK:
            await state.clear()
            prompt = await calendar_service.get_tournament_prompt(callback_data.prompt_id)
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer(
                    format_admin_calendar_prompt(prompt),
                    reply_markup=keyboards.manual_tournaments_prompt_keyboard(prompt),
                )
            await callback.answer()
            return

        await state.clear()
        action = CalendarPromptAction(callback_data.action.value)
        resolved_prompt = await calendar_service.resolve_prompt(
            prompt_id=callback_data.prompt_id,
            admin_telegram_id=callback.from_user.id,
            action=action,
        )
    except AdminAccessDeniedError:
        await callback.answer(texts.admin.INSUFFICIENT_RIGHTS, show_alert=True)
        return
    except CalendarPromptNotFoundError:
        await callback.answer(texts.admin.CALENDAR_PROMPT_STALE, show_alert=True)
        return
    except CalendarPromptAlreadyResolvedError:
        await callback.answer(
            texts.admin.CALENDAR_PROMPT_ALREADY_RESOLVED,
            show_alert=True,
        )
        return
    except CalendarTournamentDateAlreadyExistsError:
        await callback.answer(texts.admin.ADMIN_CALENDAR_TOURNAMENT_DATE_EXISTS)
        if callback.message is not None:
            await callback.message.answer(texts.admin.ADMIN_CALENDAR_TOURNAMENT_DATE_EXISTS)
        return
    except CalendarWeeklyPromptEmptyError:
        await callback.answer(texts.admin.CALENDAR_WEEKLY_PROMPT_EMPTY)
        if callback.message is not None:
            await callback.message.answer(texts.admin.CALENDAR_WEEKLY_PROMPT_EMPTY)
        return
    except (
        CalendarDefaultTournamentTypeNotFoundError,
        CalendarWeeklyPendingConflictError,
        CalendarWeeklyPromptIntegrityError,
    ):
        await callback.answer(texts.admin.CALENDAR_PROMPT_NOT_FOUND, show_alert=True)
        return

    if callback_data.action == keyboards.CalendarPromptAction.CONFIRM:
        result_text = (
            texts.admin.ADMIN_CALENDAR_TOURNAMENTS_CREATED
            if resolved_prompt.kind == "tournaments_proposal"
            else texts.admin.CALENDAR_PROMPT_CONFIRMED
        )
        await callback.answer(result_text)
        if callback.message is not None:
            await _delete_callback_message(callback)
            await callback.message.answer(format_created_tournaments_prompt(resolved_prompt))
            if resolved_prompt.kind == "tournaments_proposal":
                schedule = await calendar_service.get_created_weekly_schedule(
                    callback_data.prompt_id
                )
                for schedule_message in format_public_weekly_schedule(schedule):
                    await callback.message.answer(schedule_message)
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
    state: FSMContext,
) -> None:
    try:
        await user_service.require_superadmin(callback.from_user.id)
    except AdminAccessDeniedError:
        await callback.answer(texts.admin.INSUFFICIENT_RIGHTS, show_alert=True)
        return

    await _delete_callback_message(callback)

    if callback_data.action == keyboards.AdminCalendarAction.CANCEL:
        await state.clear()
        await callback.answer(texts.admin.ADMIN_CALENDAR_CANCELLED)
        if callback.message is not None:
            await callback.message.answer(texts.admin.ADMIN_CALENDAR_CANCELLED)
        return

    if callback_data.action == keyboards.AdminCalendarAction.SEASONS:
        try:
            proposal = await season_service.create_season_proposal(callback.from_user.id)
        except AdminAccessDeniedError:
            await state.clear()
            await callback.answer(texts.admin.INSUFFICIENT_RIGHTS, show_alert=True)
            return
        except (SeasonScoringConfigAmbiguousError, SeasonScoringConfigNotFoundError):
            await callback.answer(texts.admin.ADMIN_CALENDAR_EMPTY_SEASONS)
            if callback.message is not None:
                await callback.message.answer(texts.admin.ADMIN_CALENDAR_EMPTY_SEASONS)
            return

        await state.clear()
        await callback.answer()
        if callback.message is not None:
            await callback.message.answer(
                format_season_proposal(proposal),
                reply_markup=keyboards.season_open_confirmation_keyboard(proposal.id),
            )
        return

    try:
        prompt = await calendar_service.create_weekly_tournament_prompt()
    except CalendarTournamentDateAlreadyExistsError:
        await callback.answer(texts.admin.ADMIN_CALENDAR_TOURNAMENT_DATE_EXISTS)
        if callback.message is not None:
            await callback.message.answer(texts.admin.ADMIN_CALENDAR_TOURNAMENT_DATE_EXISTS)
        return
    except (
        CalendarDefaultTournamentTypeNotFoundError,
        CalendarWeeklyPendingConflictError,
        CalendarWeeklyPromptIntegrityError,
    ):
        await callback.answer(texts.admin.CALENDAR_PROMPT_NOT_FOUND, show_alert=True)
        return

    await state.clear()
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(
            format_admin_calendar_prompt(prompt),
            reply_markup=keyboards.manual_tournaments_prompt_keyboard(prompt),
        )


@router.message(CalendarSeasonProposalEditStates.entering_name)
async def enter_season_proposal_name(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return

    data = await state.get_data()
    prompt_id = data.get("season_proposal_id")
    if not isinstance(prompt_id, int):
        await state.clear()
        await message.answer(texts.admin.ADMIN_CALENDAR_SEASON_ALREADY_HANDLED)
        return

    try:
        await user_service.require_superadmin(message.from_user.id)
        proposal = await season_service.update_season_proposal_name(
            prompt_id=prompt_id,
            name=message.text or "",
        )
    except AdminAccessDeniedError:
        await state.clear()
        await message.answer(texts.admin.INSUFFICIENT_RIGHTS)
        return
    except SeasonNameInvalidError:
        await message.answer(texts.admin.ADMIN_CALENDAR_ENTER_SEASON_NEW_NAME)
        return
    except (SeasonProposalNotFoundError, SeasonProposalAlreadyResolvedError):
        await state.clear()
        await message.answer(texts.admin.ADMIN_CALENDAR_SEASON_ALREADY_HANDLED)
        return

    await state.clear()
    await message.answer(
        format_season_proposal(proposal),
        reply_markup=keyboards.season_open_confirmation_keyboard(proposal.id),
    )


@router.message(CalendarSeasonProposalEditStates.entering_starts_at)
async def enter_season_proposal_starts_at(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return

    data = await state.get_data()
    prompt_id = data.get("season_proposal_id")
    if not isinstance(prompt_id, int):
        await state.clear()
        await message.answer(texts.admin.ADMIN_CALENDAR_SEASON_ALREADY_HANDLED)
        return

    try:
        await user_service.require_superadmin(message.from_user.id)
        starts_at = parse_admin_date(message.text or "")
        proposal = await season_service.update_season_proposal_start_date(
            prompt_id=prompt_id,
            starts_at=starts_at,
        )
    except AdminAccessDeniedError:
        await state.clear()
        await message.answer(texts.admin.INSUFFICIENT_RIGHTS)
        return
    except SeasonStartDateError:
        await message.answer(texts.admin.ADMIN_CALENDAR_SEASON_START_INVALID)
        return
    except (SeasonProposalNotFoundError, SeasonProposalAlreadyResolvedError):
        await state.clear()
        await message.answer(texts.admin.ADMIN_CALENDAR_SEASON_ALREADY_HANDLED)
        return
    except ValueError:
        await message.answer(texts.admin.ADMIN_CALENDAR_INVALID_DATE)
        return

    await state.clear()
    await message.answer(
        format_season_proposal(proposal),
        reply_markup=keyboards.season_open_confirmation_keyboard(proposal.id),
    )


@router.callback_query(keyboards.SeasonOpenCallback.filter())
async def select_season_open_action(
    callback: CallbackQuery,
    callback_data: keyboards.SeasonOpenCallback,
    state: FSMContext,
) -> None:
    if callback_data.action == keyboards.SeasonOpenAction.CANCEL:
        try:
            await season_service.cancel_season_proposal(
                admin_telegram_id=callback.from_user.id,
                prompt_id=callback_data.prompt_id,
            )
        except AdminAccessDeniedError:
            await state.clear()
            await callback.answer(texts.admin.INSUFFICIENT_RIGHTS, show_alert=True)
            return
        except (SeasonProposalNotFoundError, SeasonProposalAlreadyResolvedError):
            await callback.answer(
                texts.admin.ADMIN_CALENDAR_SEASON_ALREADY_HANDLED,
                show_alert=True,
            )
            return

        await state.clear()
        await callback.answer(texts.admin.ADMIN_CALENDAR_CANCELLED)
        if callback.message is not None:
            await _delete_callback_message(callback)
            await callback.message.answer(texts.admin.ADMIN_CALENDAR_CANCELLED)
        return

    if callback_data.action == keyboards.SeasonOpenAction.CHANGE:
        await state.clear()
        await callback.answer()
        if callback.message is not None:
            await _delete_callback_message(callback)
            await callback.message.answer(
                texts.admin.ADMIN_CALENDAR_EDIT_MENU,
                reply_markup=keyboards.season_proposal_change_keyboard(callback_data.prompt_id),
            )
        return

    if callback_data.action == keyboards.SeasonOpenAction.NAME:
        await state.set_state(CalendarSeasonProposalEditStates.entering_name)
        await state.update_data(season_proposal_id=callback_data.prompt_id)
        await callback.answer()
        if callback.message is not None:
            await _delete_callback_message(callback)
            await callback.message.answer(texts.admin.ADMIN_CALENDAR_ENTER_SEASON_NEW_NAME)
        return

    if callback_data.action == keyboards.SeasonOpenAction.STARTS_AT:
        await state.set_state(CalendarSeasonProposalEditStates.entering_starts_at)
        await state.update_data(season_proposal_id=callback_data.prompt_id)
        await callback.answer()
        if callback.message is not None:
            await _delete_callback_message(callback)
            await callback.message.answer(texts.admin.ADMIN_CALENDAR_ENTER_SEASON_NEW_START)
        return

    if callback_data.action == keyboards.SeasonOpenAction.BACK:
        try:
            proposal = await season_service.get_season_proposal(callback_data.prompt_id)
        except (SeasonProposalNotFoundError, SeasonProposalAlreadyResolvedError):
            await callback.answer(
                texts.admin.ADMIN_CALENDAR_SEASON_ALREADY_HANDLED,
                show_alert=True,
            )
            return
        await state.clear()
        await callback.answer()
        if callback.message is not None:
            await _delete_callback_message(callback)
            await callback.message.answer(
                format_season_proposal(proposal),
                reply_markup=keyboards.season_open_confirmation_keyboard(proposal.id),
            )
        return

    try:
        season = await season_service.confirm_season_proposal(
            admin_telegram_id=callback.from_user.id,
            prompt_id=callback_data.prompt_id,
        )
    except SeasonNameAlreadyExistsError:
        await callback.answer(texts.admin.ADMIN_CALENDAR_SEASON_NAME_EXISTS, show_alert=True)
        return
    except SeasonNameInvalidError:
        await callback.answer(texts.admin.ADMIN_CALENDAR_ENTER_SEASON_NEW_NAME, show_alert=True)
        return
    except SeasonScoringConfigNotFoundError:
        await callback.answer(
            texts.admin.ADMIN_CALENDAR_SCORING_CONFIG_NOT_FOUND,
            show_alert=True,
        )
        return
    except (SeasonDateOverlapError, SeasonScheduledConflictError, SeasonStartDateError):
        await callback.answer(texts.admin.ADMIN_CALENDAR_SEASON_START_INVALID, show_alert=True)
        return
    except SeasonConflictError:
        await callback.answer(texts.admin.ADMIN_CALENDAR_SEASON_CONFLICT, show_alert=True)
        return
    except SeasonProposalInvalidPayloadError:
        await callback.answer(texts.admin.ADMIN_CALENDAR_SEASON_ALREADY_HANDLED, show_alert=True)
        return
    except (SeasonProposalNotFoundError, SeasonProposalAlreadyResolvedError):
        await callback.answer(texts.admin.ADMIN_CALENDAR_SEASON_ALREADY_HANDLED, show_alert=True)
        return
    except AdminAccessDeniedError:
        await state.clear()
        await callback.answer(texts.admin.INSUFFICIENT_RIGHTS, show_alert=True)
        return

    await state.clear()
    await callback.answer(texts.admin.ADMIN_CALENDAR_SEASON_CREATED)
    if callback.message is not None:
        await _delete_callback_message(callback)
        await callback.message.answer(format_created_season(season))


@router.callback_query(keyboards.TournamentPromptDayEditCallback.filter())
async def select_tournament_prompt_day(
    callback: CallbackQuery,
    callback_data: keyboards.TournamentPromptDayEditCallback,
    state: FSMContext,
) -> None:
    try:
        await user_service.require_superadmin(callback.from_user.id)
        edit_view = await calendar_service.get_weekly_prompt_day_edit_options(
            prompt_id=callback_data.prompt_id,
            tournament_date=date.fromisoformat(callback_data.tournament_date),
        )
    except AdminAccessDeniedError:
        await state.clear()
        await callback.answer(texts.admin.INSUFFICIENT_RIGHTS, show_alert=True)
        return
    except (
        ValueError,
        CalendarPromptInvalidPayloadError,
        CalendarPromptNotFoundError,
        CalendarPromptAlreadyResolvedError,
        CalendarTournamentDateNotInPromptError,
    ):
        await callback.answer(texts.admin.CALENDAR_PROMPT_STALE, show_alert=True)
        return

    await state.clear()
    await callback.answer()
    if callback.message is not None:
        await _delete_callback_message(callback)
        await callback.message.answer(
            texts.admin.admin_calendar_tournament_type_prompt(edit_view.tournament_date),
            reply_markup=keyboards.tournament_type_edit_keyboard(edit_view),
        )


@router.callback_query(keyboards.TournamentTypeEditCallback.filter())
async def select_tournament_type(
    callback: CallbackQuery,
    callback_data: keyboards.TournamentTypeEditCallback,
    state: FSMContext,
) -> None:
    try:
        await user_service.require_superadmin(callback.from_user.id)
        prompt = await calendar_service.update_weekly_prompt_day_type(
            prompt_id=callback_data.prompt_id,
            tournament_date=date.fromisoformat(callback_data.tournament_date),
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
    except (
        ValueError,
        CalendarPromptInvalidPayloadError,
        CalendarTournamentDateNotInPromptError,
    ):
        await callback.answer(texts.admin.CALENDAR_PROMPT_STALE, show_alert=True)
        return

    await state.clear()
    await callback.answer(texts.admin.CALENDAR_PROMPT_CONFIRMED)
    if callback.message is not None:
        await _delete_callback_message(callback)
        await callback.message.answer(
            format_admin_calendar_prompt(prompt),
            reply_markup=keyboards.manual_tournaments_prompt_keyboard(prompt),
        )


@router.message(AdminTournamentRegistrationStates.entering_player_search)
async def enter_admin_registration_player_search(
    message: Message,
    state: FSMContext,
) -> None:
    if message.from_user is None:
        return

    data = await state.get_data()
    tournament_id = int(data["admin_registration_tournament_id"])
    query = " ".join((message.text or "").split())
    if not query:
        await message.answer(texts.admin.ADMIN_TOURNAMENT_REGISTRATION_SEARCH_PROMPT)
        return

    try:
        tournaments = await tournament_service.list_registration_tournaments_for_admin(
            message.from_user.id
        )
        tournament = next(
            (tournament for tournament in tournaments if tournament.id == tournament_id),
            None,
        )
        if tournament is None:
            raise TournamentUnavailableError

        players = await tournament_service.search_players_for_admin_registration(
            admin_telegram_id=message.from_user.id,
            query=query,
        )
    except AdminAccessDeniedError:
        await state.clear()
        await message.answer(texts.admin.ACCESS_DENIED)
        return
    except TournamentUnavailableError:
        await state.clear()
        await message.answer(texts.admin.ADMIN_TOURNAMENT_REGISTRATION_NOT_FOUND)
        return

    await state.clear()
    page = pagination_service.paginate(
        players,
        page=0,
        page_size=keyboards.ADMIN_TOURNAMENT_REGISTRATION_PAGE_SIZE,
    )
    title = (
        texts.admin.ADMIN_TOURNAMENT_REGISTRATION_SEARCH_RESULTS_TITLE
        if players
        else texts.admin.ADMIN_TOURNAMENT_REGISTRATION_SEARCH_EMPTY
    )
    await message.answer(
        format_admin_tournament_registration_player_list(
            tournament,
            page,
            title=title,
        ),
        reply_markup=keyboards.admin_tournament_registration_player_keyboard(
            tournament.id,
            page,
            search_again=True,
        ),
    )


@router.message(AdminResultStates.entering_manual_value)
async def enter_result_manual_value(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return

    data = await state.get_data()
    tournament_id = int(data["result_tournament_id"])
    player_id = int(data["result_player_id"])
    page_number = int(data.get("result_page", 0))
    field = keyboards.AdminResultField(str(data["result_field"]))
    try:
        value = parse_result_manual_value(
            message.text or "",
            field=field,
        )
        draft = await result_service.update_player_result_field(
            admin_telegram_id=message.from_user.id,
            tournament_id=tournament_id,
            player_id=player_id,
            field=to_result_field(field),
            value=value,
        )
    except AdminAccessDeniedError:
        await state.clear()
        await message.answer(texts.admin.ACCESS_DENIED)
        return
    except ResultTournamentNotFoundError:
        await state.clear()
        await message.answer(texts.admin.ADMIN_RESULTS_NOT_FOUND)
        return
    except (ResultInvalidPlayerDataError, ResultUserNotFoundError, ValueError):
        await message.answer(texts.admin.ADMIN_RESULTS_INVALID_MANUAL_VALUE[field.value])
        return

    await state.clear()
    player = ResultService.find_result_player(draft, player_id)
    if player is None:
        await message.answer(texts.admin.PLAYER_NOT_FOUND)
        return
    await _delete_message_by_id(
        message,
        int(data.get("result_prompt_message_id", 0)),
    )
    await message.answer(texts.admin.ADMIN_RESULTS_SAVED)
    await message.answer(
        format_admin_result_player_detail(draft, player),
        reply_markup=keyboards.admin_result_player_fields_keyboard(
            draft,
            player,
            page_number,
        ),
    )


@router.message(AdminResultStates.entering_registered_check_in_search)
async def enter_registered_check_in_search(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return
    data = await state.get_data()
    tournament_id = int(data["check_in_tournament_id"])
    try:
        players = await tournament_participant_service.search_registered(
            admin_telegram_id=message.from_user.id,
            tournament_id=tournament_id,
            query=message.text or "",
        )
    except AdminAccessDeniedError:
        await state.clear()
        await message.answer(texts.admin.ACCESS_DENIED)
        return
    except (TournamentCheckInNotFoundError, TournamentCheckInClosedError):
        await state.clear()
        await message.answer(texts.admin.ADMIN_RESULTS_NOT_FOUND)
        return

    await state.clear()
    if not players:
        await message.answer("Игроки не найдены.")
        return
    await message.answer(
        "Нашел среди зарегистрированных:",
        reply_markup=keyboards.admin_check_in_search_results_keyboard(
            tournament_id=tournament_id,
            players=players,
            action=keyboards.AdminCheckInAction.TOGGLE_REGISTERED,
        ),
    )


@router.message(AdminResultStates.entering_database_check_in_search)
async def enter_database_check_in_search(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return
    data = await state.get_data()
    tournament_id = int(data["check_in_tournament_id"])
    try:
        players = await tournament_participant_service.search_users(
            admin_telegram_id=message.from_user.id,
            tournament_id=tournament_id,
            query=message.text or "",
        )
    except AdminAccessDeniedError:
        await state.clear()
        await message.answer(texts.admin.ACCESS_DENIED)
        return
    except (TournamentCheckInNotFoundError, TournamentCheckInClosedError):
        await state.clear()
        await message.answer(texts.admin.ADMIN_RESULTS_NOT_FOUND)
        return

    await state.clear()
    if not players:
        await message.answer("Игроки не найдены.")
        return
    await message.answer(
        "Нашел игроков в базе:",
        reply_markup=keyboards.admin_check_in_search_results_keyboard(
            tournament_id=tournament_id,
            players=players,
            action=keyboards.AdminCheckInAction.ADD_EXISTING,
        ),
    )


@router.message(AdminResultStates.entering_new_check_in_player)
async def enter_new_check_in_player(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return
    data = await state.get_data()
    tournament_id = int(data["check_in_tournament_id"])
    try:
        view = await tournament_participant_service.create_user_and_check_in(
            admin_telegram_id=message.from_user.id,
            tournament_id=tournament_id,
            display_name=message.text or "",
        )
    except AdminAccessDeniedError:
        await state.clear()
        await message.answer(texts.admin.ACCESS_DENIED)
        return
    except (TournamentCheckInNotFoundError, TournamentCheckInClosedError):
        await state.clear()
        await message.answer(texts.admin.ADMIN_RESULTS_NOT_FOUND)
        return
    except ValueError:
        await message.answer("Имя игрока некорректное.")
        return

    await state.clear()
    page = pagination_service.paginate(
        view.players,
        page=0,
        page_size=keyboards.ADMIN_RESULT_PAGE_SIZE,
    )
    await message.answer("Игрок добавлен в состав турнира.")
    await message.answer(
        format_tournament_check_in(view),
        reply_markup=keyboards.admin_check_in_keyboard(view, page),
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


async def _delete_message_by_id(message: Message, message_id: int) -> None:
    if message_id <= 0:
        return
    try:
        await message.bot.delete_message(
            chat_id=message.chat.id,
            message_id=message_id,
        )
    except TelegramBadRequest:
        pass


def parse_admin_date(value: str) -> date:
    match = re.fullmatch(r"(\d{1,2})\.(\d{2})\.(\d{4})", value.strip())
    if match is None:
        raise ValueError
    day, month, year = (int(part) for part in match.groups())
    return date(year, month, day)


def parse_result_manual_value(value: str, *, field: keyboards.AdminResultField) -> int:
    result = parse_nonnegative_int(value)
    if field == keyboards.AdminResultField.PLACE and result not in {1, 2, 3, 4, 5}:
        raise ValueError
    return result


def result_field_name(field: keyboards.AdminResultField) -> str:
    return {
        keyboards.AdminResultField.KNOCKOUTS: "🥊",
        keyboards.AdminResultField.BIG_KNOCKOUTS: "👑🥊",
        keyboards.AdminResultField.BONUS: "бонус",
        keyboards.AdminResultField.PLACE: "место",
    }[field]


def to_result_field(field: keyboards.AdminResultField) -> ResultField:
    return ResultField(field.value)


def parse_nonnegative_int(value: str) -> int:
    normalized = re.sub(r"\s+", "", value)
    if not normalized.isdecimal():
        raise ValueError
    return int(normalized)
