from aiogram.fsm.state import State, StatesGroup


class RegistrationStates(StatesGroup):
    entering_new_display_name = State()
    entering_link_name = State()


class CalendarSeasonEditStates(StatesGroup):
    entering_value = State()


class CalendarTournamentEditStates(StatesGroup):
    entering_economy = State()
    entering_rebuys = State()


class AdminResultStates(StatesGroup):
    entering_pool = State()
    entering_manual_value = State()


class AdminTournamentRegistrationStates(StatesGroup):
    entering_player_search = State()
