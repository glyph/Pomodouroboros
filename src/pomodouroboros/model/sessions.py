# -*- test-case-name: pomodouroboros.model.test.test_sessions -*-
from __future__ import annotations
from dataclasses import dataclass
from datetime import timedelta
from enum import IntEnum
from zoneinfo import ZoneInfo
from typing import TYPE_CHECKING

from datetype import DateTime, Time
from fritter.boundaries import Day
from fritter.repeat.rules.datetimes import EachWeekOn

if TYPE_CHECKING:
    from .ideal import IdealScoreInfo
    from .nexus import Nexus


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

    def idealScoreFor(self, nexus: Nexus) -> IdealScoreInfo:
        from .ideal import idealScore
        return idealScore(nexus, self.start, self.end)


@dataclass
class DailySessionRule:
    dailyStart: Time[ZoneInfo]
    dailyEnd: Time[ZoneInfo]
    days: set[Weekday]

    def nextAutomaticSession(
        self, fromTimestamp: DateTime[ZoneInfo]
    ) -> Session | None:
        assert self.dailyStart.tzinfo == fromTimestamp.tzinfo
        assert self.dailyEnd.tzinfo == fromTimestamp.tzinfo
        if not self.days:
            return None
        startRule = EachWeekOn(
            {getattr(Day, each.name.upper()) for each in self.days},
            hour=self.dailyStart.hour,
            minute=self.dailyStart.minute,
            second=self.dailyStart.second,
        )
        endRule = EachWeekOn(
            {getattr(Day, each.name.upper()) for each in self.days},
            hour=self.dailyEnd.hour,
            minute=self.dailyEnd.minute,
            second=self.dailyEnd.second,
        )
        startSteps, startNextRefs = startRule(fromTimestamp, fromTimestamp + timedelta(days=7))
        if not startSteps:
            return None
        endSteps, endNextRefs = endRule(startSteps[0], startSteps[0] + timedelta(days=7))
        if not endSteps:
            return None
        return Session(startSteps[0].timestamp(), endSteps[0].timestamp(), True)
