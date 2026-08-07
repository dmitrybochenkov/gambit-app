from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.telegram.formatters import tournaments as tournament_fmt
from app.bot.telegram.handlers.user.shared import (
    delete_message as _delete_message,
)
from app.bot.telegram.keyboards import labels
from app.bot.telegram.keyboards.user import tournaments as user_tournaments_kb
from app.bot.telegram.texts.user import tournaments as text
from app.services.pagination import pagination_service
from app.services.tournament_service import (
    TournamentCancellationUnavailableError,
    TournamentRegistrationAlreadyCheckedInError,
    TournamentRegistrationNotAllowedError,
    TournamentScheduleNotAllowedError,
    TournamentUnavailableError,
    tournament_service,
)

router = Router(name="user.tournaments")


@router.message(F.text == labels.MAIN_SCHEDULE)
async def show_tournament_schedule(message: Message) -> None:
    if message.from_user is None:
        return

    try:
        tournaments = await tournament_service.get_schedule_for_player(message.from_user.id)
    except TournamentScheduleNotAllowedError:
        await message.answer(text.SCHEDULE_UNAVAILABLE)
        return

    await message.answer(tournament_fmt.schedule(tournaments))


@router.message(F.text == labels.MAIN_REGISTER)
async def show_tournaments_for_registration(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return

    try:
        tournaments = await tournament_service.get_registration_options_for_player(
            message.from_user.id
        )
    except TournamentRegistrationNotAllowedError:
        await message.answer(text.TOURNAMENT_REGISTRATION_UNAVAILABLE)
        return

    if not tournaments:
        await message.answer(text.TOURNAMENT_REGISTRATION_EMPTY)
        return

    registered_tournaments = await tournament_service.get_player_upcoming_registrations(
        message.from_user.id
    )
    registered_tournament_ids = {tournament.id for tournament in registered_tournaments}
    selected_tournament_ids = [
        tournament.id for tournament in tournaments if tournament.id in registered_tournament_ids
    ]
    await state.update_data(tournament_registration_selection=selected_tournament_ids)
    page = pagination_service.paginate(
        tournaments,
        page=0,
        page_size=user_tournaments_kb.TOURNAMENT_LIST_PAGE_SIZE,
    )
    await message.answer(
        text.TOURNAMENT_REGISTRATION_PROMPT,
        reply_markup=user_tournaments_kb.tournament_registration_keyboard(
            page,
            set(selected_tournament_ids),
        ),
    )


@router.callback_query(user_tournaments_kb.TournamentRegistrationCallback.filter())
async def register_for_tournament(
    callback: CallbackQuery,
    callback_data: user_tournaments_kb.TournamentRegistrationCallback,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    selected_tournament_ids = set(data.get("tournament_registration_selection", []))
    if callback_data.action == user_tournaments_kb.TournamentListAction.PAGE:
        answer = None
    elif callback_data.tournament_id in selected_tournament_ids:
        selected_tournament_ids.remove(callback_data.tournament_id)
        answer = text.TOURNAMENT_REMOVED_FROM_SELECTION
    else:
        selected_tournament_ids.add(callback_data.tournament_id)
        answer = text.TOURNAMENT_ADDED_TO_SELECTION

    try:
        tournaments = await tournament_service.get_registration_options_for_player(
            callback.from_user.id
        )
    except TournamentRegistrationNotAllowedError:
        await callback.answer(
            text.TOURNAMENT_REGISTRATION_ACTIVE_ONLY,
            show_alert=True,
        )
        return
    available_ids = {tournament.id for tournament in tournaments}
    selected_tournament_ids &= available_ids
    await state.update_data(tournament_registration_selection=sorted(selected_tournament_ids))
    page = pagination_service.paginate(
        tournaments,
        page=callback_data.page,
        page_size=user_tournaments_kb.TOURNAMENT_LIST_PAGE_SIZE,
    )

    if callback.message is not None:
        await callback.message.edit_reply_markup(
            reply_markup=user_tournaments_kb.tournament_registration_keyboard(
                page,
                selected_tournament_ids,
            )
        )
    if answer is None:
        await callback.answer()
    else:
        await callback.answer(answer)


@router.callback_query(F.data == user_tournaments_kb.CONFIRM_TOURNAMENT_REGISTRATION_CALLBACK)
async def confirm_tournament_registration(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    tournament_ids = data.get("tournament_registration_selection", [])
    if not tournament_ids:
        await callback.answer(text.TOURNAMENT_SELECTION_EMPTY, show_alert=True)
        return

    try:
        tournaments = await tournament_service.register_player_for_tournaments(
            telegram_id=callback.from_user.id,
            tournament_ids=tournament_ids,
        )
    except TournamentRegistrationNotAllowedError:
        await callback.answer(
            text.TOURNAMENT_REGISTRATION_ACTIVE_ONLY,
            show_alert=True,
        )
        return
    except TournamentUnavailableError:
        await callback.answer(text.TOURNAMENT_UNAVAILABLE, show_alert=True)
        return
    await state.update_data(tournament_registration_selection=[])
    await callback.answer(text.ACTION_DONE)
    if callback.message is not None:
        await _delete_message(callback.message)
        await callback.message.answer(
            text.registration_success(
                [tournament_fmt.label(tournament) for tournament in tournaments]
            )
        )


@router.callback_query(F.data == user_tournaments_kb.CANCEL_TOURNAMENT_REGISTRATION_CALLBACK)
async def cancel_tournament_registration_selection(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    await state.update_data(tournament_registration_selection=[])
    await callback.answer(text.TOURNAMENT_REGISTRATION_CANCELLED)
    if callback.message is not None:
        await _delete_message(callback.message)
        await callback.message.answer(text.TOURNAMENT_REGISTRATION_CANCELLED)


@router.message(F.text == labels.MAIN_CANCEL_REGISTRATION)
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
        await message.answer(text.TOURNAMENT_CANCELLATION_UNAVAILABLE)
        return

    if not tournaments:
        await message.answer(text.TOURNAMENT_CANCELLATION_EMPTY)
        return

    await state.update_data(tournament_cancellation_selection=[])
    page = pagination_service.paginate(
        tournaments,
        page=0,
        page_size=user_tournaments_kb.TOURNAMENT_LIST_PAGE_SIZE,
    )
    await message.answer(
        text.TOURNAMENT_CANCELLATION_PROMPT,
        reply_markup=user_tournaments_kb.tournament_cancellation_keyboard(page),
    )


@router.callback_query(user_tournaments_kb.TournamentCancellationCallback.filter())
async def select_tournament_for_cancellation(
    callback: CallbackQuery,
    callback_data: user_tournaments_kb.TournamentCancellationCallback,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    selected_tournament_ids = set(data.get("tournament_cancellation_selection", []))
    if callback_data.action == user_tournaments_kb.TournamentListAction.PAGE:
        answer = None
    elif callback_data.tournament_id in selected_tournament_ids:
        selected_tournament_ids.remove(callback_data.tournament_id)
        answer = text.TOURNAMENT_REMOVED_FROM_SELECTION
    else:
        selected_tournament_ids.add(callback_data.tournament_id)
        answer = text.TOURNAMENT_ADDED_TO_SELECTION

    try:
        tournaments = await tournament_service.get_player_upcoming_registrations(
            callback.from_user.id
        )
    except TournamentRegistrationNotAllowedError:
        await callback.answer(
            text.TOURNAMENT_CANCELLATION_ACTIVE_ONLY,
            show_alert=True,
        )
        return

    available_ids = {tournament.id for tournament in tournaments}
    selected_tournament_ids &= available_ids
    await state.update_data(tournament_cancellation_selection=sorted(selected_tournament_ids))
    page = pagination_service.paginate(
        tournaments,
        page=callback_data.page,
        page_size=user_tournaments_kb.TOURNAMENT_LIST_PAGE_SIZE,
    )
    if callback.message is not None:
        await callback.message.edit_reply_markup(
            reply_markup=user_tournaments_kb.tournament_cancellation_keyboard(
                page,
                selected_tournament_ids,
            )
        )
    if answer is None:
        await callback.answer()
    else:
        await callback.answer(answer)


@router.callback_query(F.data == user_tournaments_kb.CONFIRM_TOURNAMENT_CANCELLATION_CALLBACK)
async def confirm_tournament_cancellation(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    tournament_ids = data.get("tournament_cancellation_selection", [])
    if not tournament_ids:
        await callback.answer(text.TOURNAMENT_SELECTION_EMPTY, show_alert=True)
        return

    try:
        tournaments = await tournament_service.cancel_player_tournament_registrations(
            telegram_id=callback.from_user.id,
            tournament_ids=tournament_ids,
        )
    except TournamentRegistrationNotAllowedError:
        await callback.answer(
            text.TOURNAMENT_CANCELLATION_ACTIVE_ONLY,
            show_alert=True,
        )
        return
    except TournamentCancellationUnavailableError:
        await callback.answer(
            text.TOURNAMENT_CANCELLATION_UNAVAILABLE_ITEM,
            show_alert=True,
        )
        return
    except TournamentRegistrationAlreadyCheckedInError:
        await callback.answer(
            text.TOURNAMENT_CANCELLATION_ALREADY_CHECKED_IN,
            show_alert=True,
        )
        return

    await state.update_data(tournament_cancellation_selection=[])
    await callback.answer(text.ACTION_DONE)
    if callback.message is not None:
        await _delete_message(callback.message)
        await callback.message.answer(
            text.cancellation_success(
                [tournament_fmt.label(tournament) for tournament in tournaments]
            )
        )


@router.callback_query(F.data == user_tournaments_kb.CANCEL_TOURNAMENT_CANCELLATION_CALLBACK)
async def cancel_tournament_cancellation_selection(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    await state.update_data(tournament_cancellation_selection=[])
    await callback.answer(text.TOURNAMENT_CANCELLATION_CANCELLED)
    if callback.message is not None:
        await _delete_message(callback.message)
        await callback.message.answer(text.TOURNAMENT_CANCELLATION_CANCELLED)
