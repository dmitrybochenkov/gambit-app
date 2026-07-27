from aiogram.fsm.state import State, StatesGroup


class RegistrationStates(StatesGroup):
    entering_new_display_name = State()
    entering_link_name = State()


class CalendarSeasonProposalEditStates(StatesGroup):
    entering_name = State()
    entering_starts_at = State()


class AdminResultStates(StatesGroup):
    entering_pool = State()
    entering_manual_value = State()


class AdminTournamentRegistrationStates(StatesGroup):
    entering_player_search = State()
