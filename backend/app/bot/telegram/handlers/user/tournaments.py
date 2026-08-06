# ruff: noqa: F403,F405
from aiogram import Router

from app.bot.telegram.handlers.user.common import *  # noqa: F403

router = Router(name="user.tournaments")


@router.message(F.text == keyboards.MAIN_SCHEDULE)
async def show_tournament_schedule(message: Message) -> None:
    if message.from_user is None:
        return

    try:
        tournaments = await tournament_service.get_schedule_for_player(message.from_user.id)
    except TournamentScheduleNotAllowedError:
        await message.answer(texts.user.SCHEDULE_UNAVAILABLE)
        return

    await message.answer(format_tournament_schedule(tournaments))


@router.message(F.text == keyboards.MAIN_REGISTER)
async def show_tournaments_for_registration(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return

    try:
        tournaments = await tournament_service.get_registration_options_for_player(
            message.from_user.id
        )
    except TournamentRegistrationNotAllowedError:
        await message.answer(texts.user.TOURNAMENT_REGISTRATION_UNAVAILABLE)
        return

    if not tournaments:
        await message.answer(texts.user.TOURNAMENT_REGISTRATION_EMPTY)
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
        page_size=keyboards.TOURNAMENT_LIST_PAGE_SIZE,
    )
    await message.answer(
        texts.user.TOURNAMENT_REGISTRATION_PROMPT,
        reply_markup=keyboards.tournament_registration_keyboard(
            page,
            set(selected_tournament_ids),
        ),
    )


@router.callback_query(keyboards.TournamentRegistrationCallback.filter())
async def register_for_tournament(
    callback: CallbackQuery,
    callback_data: keyboards.TournamentRegistrationCallback,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    selected_tournament_ids = set(data.get("tournament_registration_selection", []))
    if callback_data.action == keyboards.TournamentListAction.PAGE:
        answer = None
    elif callback_data.tournament_id in selected_tournament_ids:
        selected_tournament_ids.remove(callback_data.tournament_id)
        answer = texts.user.TOURNAMENT_REMOVED_FROM_SELECTION
    else:
        selected_tournament_ids.add(callback_data.tournament_id)
        answer = texts.user.TOURNAMENT_ADDED_TO_SELECTION

    try:
        tournaments = await tournament_service.get_registration_options_for_player(
            callback.from_user.id
        )
    except TournamentRegistrationNotAllowedError:
        await callback.answer(
            texts.user.TOURNAMENT_REGISTRATION_ACTIVE_ONLY,
            show_alert=True,
        )
        return
    available_ids = {tournament.id for tournament in tournaments}
    selected_tournament_ids &= available_ids
    await state.update_data(tournament_registration_selection=sorted(selected_tournament_ids))
    page = pagination_service.paginate(
        tournaments,
        page=callback_data.page,
        page_size=keyboards.TOURNAMENT_LIST_PAGE_SIZE,
    )

    if callback.message is not None:
        await callback.message.edit_reply_markup(
            reply_markup=keyboards.tournament_registration_keyboard(
                page,
                selected_tournament_ids,
            )
        )
    if answer is None:
        await callback.answer()
    else:
        await callback.answer(answer)


@router.callback_query(F.data == keyboards.CONFIRM_TOURNAMENT_REGISTRATION_CALLBACK)
async def confirm_tournament_registration(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    tournament_ids = data.get("tournament_registration_selection", [])
    if not tournament_ids:
        await callback.answer(texts.user.TOURNAMENT_SELECTION_EMPTY, show_alert=True)
        return

    try:
        tournaments = await tournament_service.register_player_for_tournaments(
            telegram_id=callback.from_user.id,
            tournament_ids=tournament_ids,
        )
    except TournamentRegistrationNotAllowedError:
        await callback.answer(
            texts.user.TOURNAMENT_REGISTRATION_ACTIVE_ONLY,
            show_alert=True,
        )
        return
    except TournamentUnavailableError:
        await callback.answer(texts.user.TOURNAMENT_UNAVAILABLE, show_alert=True)
        return
    await state.update_data(tournament_registration_selection=[])
    await callback.answer(texts.user.ACTION_DONE)
    if callback.message is not None:
        await _delete_message(callback.message)
        await callback.message.answer(
            texts.user.tournament_registration_success(
                [format_tournament_label(tournament) for tournament in tournaments]
            )
        )


@router.callback_query(F.data == keyboards.CANCEL_TOURNAMENT_REGISTRATION_CALLBACK)
async def cancel_tournament_registration_selection(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    await state.update_data(tournament_registration_selection=[])
    await callback.answer(texts.user.TOURNAMENT_REGISTRATION_CANCELLED)
    if callback.message is not None:
        await _delete_message(callback.message)
        await callback.message.answer(texts.user.TOURNAMENT_REGISTRATION_CANCELLED)


@router.message(F.text == keyboards.MAIN_CANCEL_REGISTRATION)
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
        await message.answer(texts.user.TOURNAMENT_CANCELLATION_UNAVAILABLE)
        return

    if not tournaments:
        await message.answer(texts.user.TOURNAMENT_CANCELLATION_EMPTY)
        return

    await state.update_data(tournament_cancellation_selection=[])
    page = pagination_service.paginate(
        tournaments,
        page=0,
        page_size=keyboards.TOURNAMENT_LIST_PAGE_SIZE,
    )
    await message.answer(
        texts.user.TOURNAMENT_CANCELLATION_PROMPT,
        reply_markup=keyboards.tournament_cancellation_keyboard(page),
    )


@router.callback_query(keyboards.TournamentCancellationCallback.filter())
async def select_tournament_for_cancellation(
    callback: CallbackQuery,
    callback_data: keyboards.TournamentCancellationCallback,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    selected_tournament_ids = set(data.get("tournament_cancellation_selection", []))
    if callback_data.action == keyboards.TournamentListAction.PAGE:
        answer = None
    elif callback_data.tournament_id in selected_tournament_ids:
        selected_tournament_ids.remove(callback_data.tournament_id)
        answer = texts.user.TOURNAMENT_REMOVED_FROM_SELECTION
    else:
        selected_tournament_ids.add(callback_data.tournament_id)
        answer = texts.user.TOURNAMENT_ADDED_TO_SELECTION

    try:
        tournaments = await tournament_service.get_player_upcoming_registrations(
            callback.from_user.id
        )
    except TournamentRegistrationNotAllowedError:
        await callback.answer(
            texts.user.TOURNAMENT_CANCELLATION_ACTIVE_ONLY,
            show_alert=True,
        )
        return

    available_ids = {tournament.id for tournament in tournaments}
    selected_tournament_ids &= available_ids
    await state.update_data(tournament_cancellation_selection=sorted(selected_tournament_ids))
    page = pagination_service.paginate(
        tournaments,
        page=callback_data.page,
        page_size=keyboards.TOURNAMENT_LIST_PAGE_SIZE,
    )
    if callback.message is not None:
        await callback.message.edit_reply_markup(
            reply_markup=keyboards.tournament_cancellation_keyboard(
                page,
                selected_tournament_ids,
            )
        )
    if answer is None:
        await callback.answer()
    else:
        await callback.answer(answer)


@router.callback_query(F.data == keyboards.CONFIRM_TOURNAMENT_CANCELLATION_CALLBACK)
async def confirm_tournament_cancellation(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    tournament_ids = data.get("tournament_cancellation_selection", [])
    if not tournament_ids:
        await callback.answer(texts.user.TOURNAMENT_SELECTION_EMPTY, show_alert=True)
        return

    try:
        tournaments = await tournament_service.cancel_player_tournament_registrations(
            telegram_id=callback.from_user.id,
            tournament_ids=tournament_ids,
        )
    except TournamentRegistrationNotAllowedError:
        await callback.answer(
            texts.user.TOURNAMENT_CANCELLATION_ACTIVE_ONLY,
            show_alert=True,
        )
        return
    except TournamentCancellationUnavailableError:
        await callback.answer(
            texts.user.TOURNAMENT_CANCELLATION_UNAVAILABLE_ITEM,
            show_alert=True,
        )
        return

    await state.update_data(tournament_cancellation_selection=[])
    await callback.answer(texts.user.ACTION_DONE)
    if callback.message is not None:
        await _delete_message(callback.message)
        await callback.message.answer(
            texts.user.tournament_cancellation_success(
                [format_tournament_label(tournament) for tournament in tournaments]
            )
        )


@router.callback_query(F.data == keyboards.CANCEL_TOURNAMENT_CANCELLATION_CALLBACK)
async def cancel_tournament_cancellation_selection(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    await state.update_data(tournament_cancellation_selection=[])
    await callback.answer(texts.user.TOURNAMENT_CANCELLATION_CANCELLED)
    if callback.message is not None:
        await _delete_message(callback.message)
        await callback.message.answer(texts.user.TOURNAMENT_CANCELLATION_CANCELLED)
