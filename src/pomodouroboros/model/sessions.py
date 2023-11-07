# -*- test-case-name: pomodouroboros.model.test.test_sessions -*-
from dataclasses import dataclass
from datetime import timedelta
from enum import IntEnum, auto
from zoneinfo import ZoneInfo

from datetype import DateTime, Time


class Weekday(IntEnum):
    monday = 0
    tuesday = 1
    wednesday = 2
    thursday = 3
    friday = 4
    saturday = 5
    sunday = 6


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
    ) -> Session | None:
        if not self.days:
            return None
        tsStart = fromTimestamp.timetz()
        isEarlier = tsStart < self.dailyStart
        thisDay = Weekday(fromTimestamp.date().weekday()) in self.days
        if thisDay and isEarlier:
            startTime = DateTime.combine(
                fromTimestamp.date(), self.dailyStart
            ).timestamp()
            endTime = DateTime.combine(
                fromTimestamp.date(), self.dailyEnd
            ).timestamp()
            return Session(startTime, endTime, True)
        return self.nextAutomaticSession(
            (fromTimestamp + timedelta(days=1)).replace(
                hour=0, minute=0, second=0
            )
        )
