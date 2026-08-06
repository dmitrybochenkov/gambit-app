# ruff: noqa: F401
import logging
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
    format_admin_close_tournament_blocked,
    format_admin_close_tournament_card,
    format_admin_close_tournament_confirmation,
    format_admin_close_tournament_list,
    format_admin_closed_tournament,
    format_admin_result_field_prompt,
    format_admin_result_player_detail,
    format_admin_result_players,
    format_admin_result_tournament_list,
    format_admin_tournament_fund_error,
    format_check_in_player_notification,
    format_created_season,
    format_created_tournaments_prompt,
    format_existing_check_in_confirmation,
    format_new_check_in_confirmation,
    format_public_weekly_schedule,
    format_registered_check_in_confirmation,
    format_season_proposal,
    format_tournament_check_in,
)
from app.bot.telegram.notifications import format_registration_review
from app.bot.telegram.states import (
    AdminResultStates,
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
    FutureTournamentCannotBeClosedError,
    ResultField,
    ResultInvalidFundError,
    ResultInvalidPlayerDataError,
    ResultService,
    ResultTodayTournamentInvariantViolationError,
    ResultTodayTournamentNotFoundError,
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
from app.services.tournament_check_in_service import (
    CheckInResultView,
    TournamentCheckInClosedError,
    TournamentCheckInDuplicateNameError,
    TournamentCheckInNotFoundError,
    TournamentCheckInRegisteredUserError,
    TournamentCheckInUserNotFoundError,
    tournament_check_in_service,
)
from app.services.user_service import (
    AdminAccessDeniedError,
    RegistrationAlreadyReviewedError,
    RegistrationCandidateNotFoundError,
    UserNotFoundError,
    UserRoleAlreadyAssignedError,
    user_service,
)

RESULT_SUMMARY_PARSE_MODE = "Markdown"
logger = logging.getLogger(__name__)


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


__all__ = [name for name in globals() if not name.startswith("__")]
