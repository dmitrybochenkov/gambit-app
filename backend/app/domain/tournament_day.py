from datetime import date, timedelta

from app.common.clock import Clock


def resolve_tournament_day(clock: Clock, start_hour: int) -> date:
    current = clock.now()
    if current.hour < start_hour:
        return current.date() - timedelta(days=1)
    return current.date()
