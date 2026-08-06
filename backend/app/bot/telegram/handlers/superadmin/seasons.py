# ruff: noqa: F403,F405
from aiogram import Router

from app.bot.telegram.handlers.admin.common import *  # noqa: F403

router = Router(name="admin.seasons")


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
