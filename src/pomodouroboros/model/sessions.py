# -*- test-case-name: pomodouroboros.model.test.test_sessions -*-
from dataclasses import dataclass
from enum import IntEnum, auto
from zoneinfo import ZoneInfo

from datetype import DateTime, Time


class Weekday(IntEnum):
    monday = auto()
    tuesday = auto()
    wednesday = auto()
    thursday = auto()
    friday = auto()
    saturday = auto()
    sunday = auto()


@dataclass(frozen=True, order=True)
class Session:
    """
    A session describes a period during which the user wishes to be
    intentionally actively using the app.  During an active session, users will
    be notified of the next time their score will decrease.
    """

    start: float
    end: float
    automatic: bool


@dataclass
class DailySessionRule:
    dailyStart: Time[ZoneInfo]
    dailyEnd: Time[ZoneInfo]
    days: set[Weekday]

    def nextAutomaticSession(
        self, fromTimestamp: DateTime[ZoneInfo]
    ) -> Session:
        if self.dailyStart < fromTimestamp.timetz():
            startTime = DateTime.combine(fromTimestamp.date(), self.dailyStart).timestamp()
            endTime = DateTime.combine(fromTimestamp.date(), self.dailyEnd).timestamp()
            return Session(startTime, endTime, True)
        return self.nextAutomaticSession()
