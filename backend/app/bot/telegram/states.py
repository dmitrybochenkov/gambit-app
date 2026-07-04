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
