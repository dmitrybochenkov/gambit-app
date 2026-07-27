from aiogram.fsm.state import State, StatesGroup


class RegistrationStates(StatesGroup):
    entering_new_display_name = State()
    entering_link_name = State()


class CalendarSeasonOpenStates(StatesGroup):
    entering_name = State()
    entering_starts_at = State()


class CalendarTournamentOpenStates(StatesGroup):
    entering_date = State()
    entering_edit_date = State()


class AdminResultStates(StatesGroup):
    entering_pool = State()
    entering_manual_value = State()


class AdminTournamentRegistrationStates(StatesGroup):
    entering_player_search = State()
