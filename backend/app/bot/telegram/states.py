from aiogram.fsm.state import State, StatesGroup


class RegistrationStates(StatesGroup):
    entering_new_display_name = State()
    confirming_new_display_name = State()
    entering_link_name = State()


class AdminAddStates(StatesGroup):
    entering_candidate_name = State()


class HallOfFameStates(StatesGroup):
    entering_player_name = State()


class CalendarSeasonProposalEditStates(StatesGroup):
    entering_name = State()
    entering_starts_at = State()
    entering_initial_starts_at = State()


class AdminResultStates(StatesGroup):
    entering_manual_value = State()
    entering_tournament_fund = State()
    entering_registered_check_in_search = State()
    entering_database_check_in_search = State()
    entering_new_check_in_player = State()
    confirming_new_check_in_player = State()
