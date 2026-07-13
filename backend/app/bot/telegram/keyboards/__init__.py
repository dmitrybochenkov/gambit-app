from app.bot.telegram.keyboards.admin import (
    CalendarPromptAction,
    CalendarPromptCallback,
    RegistrationReviewAction,
    RegistrationReviewCallback,
    calendar_prompt_keyboard,
    registration_review_keyboard,
)
from app.bot.telegram.keyboards.buttons import (
    MAIN_ADDRESS,
    MAIN_ADMIN,
    MAIN_CANCEL_REGISTRATION,
    MAIN_PROFILE,
    MAIN_RATING,
    MAIN_REGISTER,
    MAIN_SCHEDULE,
)
from app.bot.telegram.keyboards.main import main_keyboard
from app.bot.telegram.keyboards.profile import ProfileCallback, profile_keyboard
from app.bot.telegram.keyboards.rating import RatingCallback, rating_keyboard
from app.bot.telegram.keyboards.registration import (
    CONFIRM_REGISTRATION_CALLBACK,
    RESTART_REGISTRATION_CALLBACK,
    RegistrationModeCallback,
    registration_confirmation_keyboard,
    registration_mode_keyboard,
)
from app.bot.telegram.keyboards.tournaments import (
    CANCEL_TOURNAMENT_CANCELLATION_CALLBACK,
    CANCEL_TOURNAMENT_REGISTRATION_CALLBACK,
    CONFIRM_TOURNAMENT_CANCELLATION_CALLBACK,
    CONFIRM_TOURNAMENT_REGISTRATION_CALLBACK,
    TournamentCancellationCallback,
    TournamentRegistrationCallback,
    tournament_cancellation_keyboard,
    tournament_registration_keyboard,
)

__all__ = [
    "CANCEL_TOURNAMENT_CANCELLATION_CALLBACK",
    "CANCEL_TOURNAMENT_REGISTRATION_CALLBACK",
    "CONFIRM_REGISTRATION_CALLBACK",
    "CONFIRM_TOURNAMENT_CANCELLATION_CALLBACK",
    "CONFIRM_TOURNAMENT_REGISTRATION_CALLBACK",
    "MAIN_ADDRESS",
    "MAIN_ADMIN",
    "MAIN_CANCEL_REGISTRATION",
    "MAIN_PROFILE",
    "MAIN_RATING",
    "MAIN_REGISTER",
    "MAIN_SCHEDULE",
    "RESTART_REGISTRATION_CALLBACK",
    "CalendarPromptAction",
    "CalendarPromptCallback",
    "ProfileCallback",
    "RatingCallback",
    "RegistrationModeCallback",
    "RegistrationReviewAction",
    "RegistrationReviewCallback",
    "TournamentCancellationCallback",
    "TournamentRegistrationCallback",
    "calendar_prompt_keyboard",
    "main_keyboard",
    "profile_keyboard",
    "rating_keyboard",
    "registration_confirmation_keyboard",
    "registration_mode_keyboard",
    "registration_review_keyboard",
    "tournament_cancellation_keyboard",
    "tournament_registration_keyboard",
]
