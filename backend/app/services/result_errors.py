class ResultInvalidCombinationRankError(ValueError):
    pass


class ResultTournamentNotFoundError(ValueError):
    pass


class ResultTodayTournamentNotFoundError(ValueError):
    pass


class ResultTodayTournamentInvariantViolationError(ValueError):
    pass


class TournamentResultsEditingUnavailableError(ValueError):
    pass


class FutureTournamentCannotBeClosedError(ValueError):
    pass


class ResultUserNotFoundError(ValueError):
    pass


class ResultInvalidFundError(ValueError):
    pass


class ResultInvalidPlayerDataError(ValueError):
    pass


class ClosedTournamentCorrectionStaleError(ValueError):
    pass


class ResultValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("\n".join(errors))


class ResultInvalidTournamentTypeRuleError(ValueError):
    pass


class ResultDuplicateNameError(ValueError):
    pass


class ResultPlayerAlreadyAddedError(ValueError):
    pass


class ResultPlayerRewardConflictError(ValueError):
    pass


class ResultCombinationAlreadyExistsError(ValueError):
    pass


class ResultCombinationNotFoundError(ValueError):
    pass
