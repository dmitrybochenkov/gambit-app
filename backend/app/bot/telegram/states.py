from enum import StrEnum

from aiogram.fsm.state import State, StatesGroup


class RegistrationMode(StrEnum):
    FULL_NAME = "full_name"
    NICKNAME = "nickname"
    BOTH = "both"


class RegistrationStates(StatesGroup):
    entering_full_name = State()
    entering_nickname = State()
    confirming = State()


class CalendarSeasonEditStates(StatesGroup):
    entering_value = State()


class CalendarTournamentEditStates(StatesGroup):
    entering_economy = State()
    entering_rebuys = State()


class AdminResultStates(StatesGroup):
    entering_pool = State()
    entering_player_result = State()


class AdminTournamentRegistrationStates(StatesGroup):
    entering_player_search = State()
