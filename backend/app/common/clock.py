from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol
from zoneinfo import ZoneInfo

from app.config import settings


class Clock(Protocol):
    def now(self) -> datetime:
        pass

    def today(self) -> date:
        pass


@dataclass(frozen=True)
class ClubClock:
    timezone_name: str = settings.club_timezone

    def now(self) -> datetime:
        return datetime.now(ZoneInfo(self.timezone_name))

    def today(self) -> date:
        return self.now().date()


@dataclass(frozen=True)
class FixedClock:
    value: datetime

    def now(self) -> datetime:
        return self.value

    def today(self) -> date:
        return self.value.date()


club_clock = ClubClock()
