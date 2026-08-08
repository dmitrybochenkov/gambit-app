import logging

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.telegram.formatters import seasons as season_fmt
from app.bot.telegram.handlers.admin.shared import (
    delete_callback_message as _delete_callback_message,
)
from app.bot.telegram.handlers.admin.shared import (
    parse_admin_date,
)
from app.bot.telegram.keyboards.superadmin import seasons as superadmin_seasons_kb
from app.bot.telegram.message_edit import edit_message_if_changed
from app.bot.telegram.states import CalendarSeasonProposalEditStates
from app.bot.telegram.texts.superadmin import panel as panel_text
from app.bot.telegram.texts.superadmin import seasons as text
from app.services.access_policy import AdminAccessDeniedError
from app.services.dto.seasons import SeasonTimelineView
from app.services.season_service import (
    SeasonConflictError,
    SeasonCurrentNotFoundError,
    SeasonDateOverlapError,
    SeasonNameAlreadyExistsError,
    SeasonNameInvalidError,
    SeasonNotFoundError,
    SeasonProposalAlreadyResolvedError,
    SeasonProposalInvalidPayloadError,
    SeasonProposalNotFoundError,
    SeasonScheduledConflictError,
    SeasonScoringConfigAmbiguousError,
    SeasonScoringConfigNotFoundError,
    SeasonStartDateError,
    season_service,
)
from app.services.user_access_service import user_access_service

logger = logging.getLogger(__name__)


router = Router(name="admin.seasons")

SEASONS_PAGE_SIZE = 5


def _season_management_keyboard(timeline: SeasonTimelineView) -> object:
    return superadmin_seasons_kb.season_management_keyboard(
        can_create=not timeline.has_future_season,
        can_delete_future=timeline.has_future_season,
        future_season_id=timeline.future_season.id if timeline.future_season is not None else None,
    )


@router.callback_query(superadmin_seasons_kb.SeasonManageCallback.filter())
async def manage_seasons(
    callback: CallbackQuery,
    callback_data: superadmin_seasons_kb.SeasonManageCallback,
    state: FSMContext,
) -> None:
    try:
        if callback_data.action == superadmin_seasons_kb.SeasonManageAction.CANCEL:
            await state.clear()
            await callback.answer(text.ADMIN_CALENDAR_CANCELLED)
            if callback.message is not None:
                await _delete_callback_message(callback)
                await callback.message.answer(text.ADMIN_CALENDAR_CANCELLED)
            return

        if callback_data.action == superadmin_seasons_kb.SeasonManageAction.LIST:
            page = await season_service.list_seasons_page_for_admin(
                callback.from_user.id,
                page=0,
                page_size=SEASONS_PAGE_SIZE,
            )
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=season_fmt.list_page(page),
                    reply_markup=superadmin_seasons_kb.season_list_keyboard(page),
                )
            return

        if callback_data.action == superadmin_seasons_kb.SeasonManageAction.LIST_PAGE:
            if callback_data.page < 0:
                timeline = await season_service.get_season_timeline(callback.from_user.id)
                await callback.answer()
                if callback.message is not None:
                    await edit_message_if_changed(
                        callback.message,
                        text=season_fmt.management(timeline),
                        reply_markup=_season_management_keyboard(timeline),
                    )
                return
            page = await season_service.list_seasons_page_for_admin(
                callback.from_user.id,
                page=callback_data.page,
                page_size=SEASONS_PAGE_SIZE,
            )
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=season_fmt.list_page(page),
                    reply_markup=superadmin_seasons_kb.season_list_keyboard(page),
                )
            return

        if callback_data.action == superadmin_seasons_kb.SeasonManageAction.DELETE_FUTURE:
            seasons_page = await season_service.list_seasons_page_for_admin(
                callback.from_user.id,
                page=0,
                page_size=1000,
            )
            season = next(
                (item for item in seasons_page.items if item.id == callback_data.season_id),
                None,
            )
            if season is None or season.lifecycle_state != "scheduled":
                raise SeasonNotFoundError
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=season_fmt.future_delete_confirmation(season),
                    reply_markup=(
                        superadmin_seasons_kb.season_delete_future_confirmation_keyboard(season.id)
                    ),
                )
            return

        timeline = await season_service.get_season_timeline(callback.from_user.id)
        if timeline.pending_proposal is not None:
            proposal = timeline.pending_proposal
        elif timeline.suggested_start is None:
            await state.set_state(CalendarSeasonProposalEditStates.entering_initial_starts_at)
            await callback.answer()
            if callback.message is not None:
                await edit_message_if_changed(
                    callback.message,
                    text=text.ADMIN_CALENDAR_ENTER_SEASON_NEW_START,
                    reply_markup=superadmin_seasons_kb.season_input_navigation_keyboard(),
                )
            return
        else:
            proposal = await season_service.create_season_proposal(callback.from_user.id)
        await state.clear()
        await callback.answer()
        if callback.message is not None:
            await edit_message_if_changed(
                callback.message,
                text=season_fmt.proposal(proposal),
                reply_markup=superadmin_seasons_kb.season_open_confirmation_keyboard(proposal.id),
            )
    except AdminAccessDeniedError:
        await state.clear()
        await callback.answer(panel_text.INSUFFICIENT_RIGHTS, show_alert=True)
    except (
        SeasonCurrentNotFoundError,
        SeasonDateOverlapError,
        SeasonScheduledConflictError,
        SeasonStartDateError,
    ):
        await callback.answer(text.ADMIN_CALENDAR_SEASON_START_INVALID, show_alert=True)
    except SeasonNotFoundError:
        await callback.answer(text.ADMIN_CALENDAR_SEASON_ALREADY_HANDLED, show_alert=True)
    except (SeasonScoringConfigAmbiguousError, SeasonScoringConfigNotFoundError):
        await callback.answer(text.ADMIN_CALENDAR_SCORING_CONFIG_NOT_FOUND, show_alert=True)


@router.callback_query(superadmin_seasons_kb.SeasonDeleteFutureCallback.filter())
async def select_future_season_delete_action(
    callback: CallbackQuery,
    callback_data: superadmin_seasons_kb.SeasonDeleteFutureCallback,
    state: FSMContext,
) -> None:
    if callback_data.action == superadmin_seasons_kb.SeasonDeleteFutureAction.CANCEL:
        await state.clear()
        await callback.answer(text.ADMIN_CALENDAR_CANCELLED)
        if callback.message is not None:
            await _delete_callback_message(callback)
            await callback.message.answer(text.ADMIN_CALENDAR_CANCELLED)
        return
    if callback_data.action == superadmin_seasons_kb.SeasonDeleteFutureAction.BACK:
        timeline = await season_service.get_season_timeline(callback.from_user.id)
        await state.clear()
        await callback.answer()
        if callback.message is not None:
            await edit_message_if_changed(
                callback.message,
                text=season_fmt.management(timeline),
                reply_markup=_season_management_keyboard(timeline),
            )
        return

    try:
        timeline = await season_service.delete_future_season(
            admin_telegram_id=callback.from_user.id,
            season_id=callback_data.season_id,
        )
    except AdminAccessDeniedError:
        await state.clear()
        await callback.answer(panel_text.INSUFFICIENT_RIGHTS, show_alert=True)
        return
    except (SeasonCurrentNotFoundError, SeasonDateOverlapError, SeasonNotFoundError):
        await callback.answer(text.ADMIN_CALENDAR_SEASON_ALREADY_HANDLED, show_alert=True)
        return
    except SeasonConflictError:
        await callback.answer(text.ADMIN_CALENDAR_SEASON_CONFLICT, show_alert=True)
        return

    await state.clear()
    await callback.answer()
    if callback.message is not None:
        await edit_message_if_changed(
            callback.message,
            text=season_fmt.management(timeline),
            reply_markup=_season_management_keyboard(timeline),
        )


@router.message(CalendarSeasonProposalEditStates.entering_name)
async def enter_season_proposal_name(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return

    data = await state.get_data()
    prompt_id = data.get("season_proposal_id")
    if not isinstance(prompt_id, int):
        await state.clear()
        await message.answer(text.ADMIN_CALENDAR_SEASON_ALREADY_HANDLED)
        return

    try:
        await user_access_service.require_superadmin(message.from_user.id)
        proposal = await season_service.update_season_proposal_name(
            admin_telegram_id=message.from_user.id,
            prompt_id=prompt_id,
            name=message.text or "",
        )
    except AdminAccessDeniedError:
        await state.clear()
        await message.answer(panel_text.INSUFFICIENT_RIGHTS)
        return
    except SeasonNameInvalidError:
        await message.answer(text.ADMIN_CALENDAR_ENTER_SEASON_NEW_NAME)
        return
    except (SeasonProposalNotFoundError, SeasonProposalAlreadyResolvedError):
        await state.clear()
        await message.answer(text.ADMIN_CALENDAR_SEASON_ALREADY_HANDLED)
        return

    await state.clear()
    await message.answer(
        season_fmt.proposal(proposal),
        reply_markup=superadmin_seasons_kb.season_open_confirmation_keyboard(proposal.id),
    )


@router.message(CalendarSeasonProposalEditStates.entering_starts_at)
async def enter_season_proposal_starts_at(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return

    data = await state.get_data()
    prompt_id = data.get("season_proposal_id")
    if not isinstance(prompt_id, int):
        await state.clear()
        await message.answer(text.ADMIN_CALENDAR_SEASON_ALREADY_HANDLED)
        return

    try:
        await user_access_service.require_superadmin(message.from_user.id)
        starts_at = parse_admin_date(message.text or "")
        proposal = await season_service.update_season_proposal_start_date(
            admin_telegram_id=message.from_user.id,
            prompt_id=prompt_id,
            starts_at=starts_at,
        )
    except AdminAccessDeniedError:
        await state.clear()
        await message.answer(panel_text.INSUFFICIENT_RIGHTS)
        return
    except SeasonStartDateError:
        await message.answer(text.ADMIN_CALENDAR_SEASON_START_INVALID)
        return
    except (SeasonProposalNotFoundError, SeasonProposalAlreadyResolvedError):
        await state.clear()
        await message.answer(text.ADMIN_CALENDAR_SEASON_ALREADY_HANDLED)
        return
    except ValueError:
        await message.answer(text.ADMIN_CALENDAR_INVALID_DATE)
        return

    await state.clear()
    await message.answer(
        season_fmt.proposal(proposal),
        reply_markup=superadmin_seasons_kb.season_open_confirmation_keyboard(proposal.id),
    )


@router.message(CalendarSeasonProposalEditStates.entering_initial_starts_at)
async def enter_initial_season_proposal_starts_at(
    message: Message,
    state: FSMContext,
) -> None:
    if message.from_user is None:
        return

    try:
        starts_at = parse_admin_date(message.text or "")
    except ValueError:
        await message.answer(text.ADMIN_CALENDAR_INVALID_DATE)
        return

    try:
        proposal = await season_service.create_season_proposal(
            admin_telegram_id=message.from_user.id,
            starts_at=starts_at,
        )
    except AdminAccessDeniedError:
        await state.clear()
        await message.answer(panel_text.INSUFFICIENT_RIGHTS)
        return
    except (SeasonDateOverlapError, SeasonScheduledConflictError, SeasonStartDateError):
        await message.answer(text.ADMIN_CALENDAR_SEASON_START_INVALID)
        return
    except (SeasonScoringConfigAmbiguousError, SeasonScoringConfigNotFoundError):
        await state.clear()
        await message.answer(text.ADMIN_CALENDAR_SCORING_CONFIG_NOT_FOUND)
        return

    await state.clear()
    await message.answer(
        season_fmt.proposal(proposal),
        reply_markup=superadmin_seasons_kb.season_open_confirmation_keyboard(proposal.id),
    )


@router.callback_query(superadmin_seasons_kb.SeasonOpenCallback.filter())
async def select_season_open_action(
    callback: CallbackQuery,
    callback_data: superadmin_seasons_kb.SeasonOpenCallback,
    state: FSMContext,
) -> None:
    if callback_data.action == superadmin_seasons_kb.SeasonOpenAction.CANCEL:
        try:
            await season_service.cancel_season_proposal(
                admin_telegram_id=callback.from_user.id,
                prompt_id=callback_data.prompt_id,
            )
        except AdminAccessDeniedError:
            await state.clear()
            await callback.answer(panel_text.INSUFFICIENT_RIGHTS, show_alert=True)
            return
        except (SeasonProposalNotFoundError, SeasonProposalAlreadyResolvedError):
            await callback.answer(
                text.ADMIN_CALENDAR_SEASON_ALREADY_HANDLED,
                show_alert=True,
            )
            return

        await state.clear()
        await callback.answer(text.ADMIN_CALENDAR_CANCELLED)
        if callback.message is not None:
            await _delete_callback_message(callback)
            await callback.message.answer(text.ADMIN_CALENDAR_CANCELLED)
        return

    if callback_data.action == superadmin_seasons_kb.SeasonOpenAction.CHANGE:
        await state.clear()
        await callback.answer()
        if callback.message is not None:
            await _delete_callback_message(callback)
            await callback.message.answer(
                text.ADMIN_CALENDAR_EDIT_MENU,
                reply_markup=superadmin_seasons_kb.season_proposal_change_keyboard(
                    callback_data.prompt_id
                ),
            )
        return

    if callback_data.action == superadmin_seasons_kb.SeasonOpenAction.NAME:
        await state.set_state(CalendarSeasonProposalEditStates.entering_name)
        await state.update_data(season_proposal_id=callback_data.prompt_id)
        await callback.answer()
        if callback.message is not None:
            await _delete_callback_message(callback)
            await callback.message.answer(
                text.ADMIN_CALENDAR_ENTER_SEASON_NEW_NAME,
                reply_markup=superadmin_seasons_kb.season_input_navigation_keyboard(
                    callback_data.prompt_id
                ),
            )
        return

    if callback_data.action == superadmin_seasons_kb.SeasonOpenAction.STARTS_AT:
        await state.set_state(CalendarSeasonProposalEditStates.entering_starts_at)
        await state.update_data(season_proposal_id=callback_data.prompt_id)
        await callback.answer()
        if callback.message is not None:
            await _delete_callback_message(callback)
            await callback.message.answer(
                text.ADMIN_CALENDAR_ENTER_SEASON_NEW_START,
                reply_markup=superadmin_seasons_kb.season_input_navigation_keyboard(
                    callback_data.prompt_id
                ),
            )
        return

    if callback_data.action == superadmin_seasons_kb.SeasonOpenAction.BACK:
        try:
            proposal = await season_service.get_season_proposal(
                admin_telegram_id=callback.from_user.id,
                prompt_id=callback_data.prompt_id,
            )
        except (SeasonProposalNotFoundError, SeasonProposalAlreadyResolvedError):
            await callback.answer(
                text.ADMIN_CALENDAR_SEASON_ALREADY_HANDLED,
                show_alert=True,
            )
            return
        await state.clear()
        await callback.answer()
        if callback.message is not None:
            await _delete_callback_message(callback)
            await callback.message.answer(
                season_fmt.proposal(proposal),
                reply_markup=superadmin_seasons_kb.season_open_confirmation_keyboard(proposal.id),
            )
        return

    try:
        season = await season_service.confirm_season_proposal(
            admin_telegram_id=callback.from_user.id,
            prompt_id=callback_data.prompt_id,
        )
    except SeasonNameAlreadyExistsError:
        await callback.answer(text.ADMIN_CALENDAR_SEASON_NAME_EXISTS, show_alert=True)
        return
    except SeasonNameInvalidError:
        await callback.answer(text.ADMIN_CALENDAR_ENTER_SEASON_NEW_NAME, show_alert=True)
        return
    except SeasonScoringConfigNotFoundError:
        await callback.answer(
            text.ADMIN_CALENDAR_SCORING_CONFIG_NOT_FOUND,
            show_alert=True,
        )
        return
    except (SeasonDateOverlapError, SeasonScheduledConflictError, SeasonStartDateError):
        await callback.answer(text.ADMIN_CALENDAR_SEASON_START_INVALID, show_alert=True)
        return
    except SeasonConflictError:
        await callback.answer(text.ADMIN_CALENDAR_SEASON_CONFLICT, show_alert=True)
        return
    except SeasonProposalInvalidPayloadError:
        await callback.answer(text.ADMIN_CALENDAR_SEASON_ALREADY_HANDLED, show_alert=True)
        return
    except (SeasonProposalNotFoundError, SeasonProposalAlreadyResolvedError):
        await callback.answer(text.ADMIN_CALENDAR_SEASON_ALREADY_HANDLED, show_alert=True)
        return
    except AdminAccessDeniedError:
        await state.clear()
        await callback.answer(panel_text.INSUFFICIENT_RIGHTS, show_alert=True)
        return

    await state.clear()
    await callback.answer(text.ADMIN_CALENDAR_SEASON_CREATED)
    if callback.message is not None:
        await _delete_callback_message(callback)
        await callback.message.answer(season_fmt.created(season))
