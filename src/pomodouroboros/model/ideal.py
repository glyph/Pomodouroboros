from __future__ import annotations
from dataclasses import dataclass
from itertools import count
from typing import Iterator, TYPE_CHECKING

from .boundaries import (
    EvaluationResult,
    NoUserInterface,
    PomStartResult,
    ScoreEvent,
)
from .debugger import debug

if TYPE_CHECKING:
    from .nexus import Nexus
    from .intention import Intention

from .intervals import (
    AnyInterval,
    Break,
    Duration,
    GracePeriod,
    Pomodoro,
)


@dataclass
class IdealScoreInfo:
    """
    Information about time remaining to the next ideal score loss.
    """

    now: float
    workPeriodEnd: float
    idealScoreNow: list[ScoreEvent]
    nextPointLoss: float | None
    idealScoreNext: list[ScoreEvent]

    def pointsLost(self) -> float:
        """
        Compute, numerically, how many points will be lost at L{self.nextPointLoss}.
        """
        return sum(each.points for each in self.idealScoreNow) - sum(
            each.points for each in self.idealScoreNext
        )


def idealFuture(
    nexus: Nexus, activityStart: float, workPeriodEnd: float
) -> Nexus:
    """
    Compute the ideal score if we were to maintain focus through the end of
    the given time period.

    @param activityStart: The point at which the user begins taking their
        next action to complete ideal future streaks.

    @param workPeriodEnd: The point beyond which we will not count points
        any more; i.e. the end of the work day.
    """
    hypothetical = nexus.cloneWithoutUI()
    debug("advancing to activity start", nexus._lastUpdateTime, activityStart)
    hypothetical.advanceToTime(activityStart)

    c = count()

    def newPlaceholder() -> Intention:
        return hypothetical.addIntention(f"placeholder {next(c)}", None)

    fillerIntentions = [
        newPlaceholder()
        for _ in range(max(0, 9 - len(hypothetical.intentions)))
    ]
    # fillerIntentions: list[Intention] = []

    def availablePlaceholder() -> Intention:
        if fillerIntentions:
            return fillerIntentions.pop(0)
        return newPlaceholder()

    while hypothetical._lastUpdateTime <= workPeriodEnd:
        workingInterval: AnyInterval | None = hypothetical._activeInterval
        if isinstance(workingInterval, (type(None), GracePeriod)):
            # We are either idle or in a grace period, so we should
            # immediately start a pomodoro.

            intention = availablePlaceholder()
            startResult = hypothetical.startPomodoro(intention)
            assert startResult in {
                PomStartResult.Started,
                PomStartResult.Continued,
            }, "invariant failed: could not actually start pomodoro"
        elif isinstance(workingInterval, (Break, Pomodoro)):
            debug("advancing to interval end", workingInterval)
            hypothetical.advanceToTime(workingInterval.endTime)
            if isinstance(workingInterval, Pomodoro):
                debug("achieving")
                hypothetical.evaluatePomodoro(
                    workingInterval, EvaluationResult.achieved
                )
            # TODO: we need to be exactly estimating every intention to get
            # maximum points.
    return hypothetical


def idealScore(nexus: Nexus, workPeriodEnd: float) -> IdealScoreInfo:
    """
    Compute the inflection point for the ideal score the user might
    achieve.  We present two hypothetical futures: one where the user
    executes perfectly, and the other where they wait long enough to lose
    some element of that perfect score, and then begins executing
    perfectly.
    """
    debug("ideal future 1")
    workPeriodBegin = nexus._lastUpdateTime
    currentIdeal = idealFuture(nexus, workPeriodBegin, workPeriodEnd)
    idealScoreNow = sorted(
        currentIdeal.scoreEvents(endTime=workPeriodEnd), key=lambda it: it.time
    )
    if not idealScoreNow:
        return IdealScoreInfo(
            now=workPeriodBegin,
            idealScoreNow=idealScoreNow,
            workPeriodEnd=workPeriodEnd,
            nextPointLoss=None,
            idealScoreNext=idealScoreNow,
        )
    latestScoreTime = idealScoreNow[-1].time
    pointLossTime = workPeriodBegin + (workPeriodEnd - latestScoreTime)
    return IdealScoreInfo(
        now=nexus._lastUpdateTime,
        idealScoreNow=idealScoreNow,
        workPeriodEnd=workPeriodEnd,
        nextPointLoss=pointLossTime,
        idealScoreNext=list(
            (
                idealFuture(nexus, pointLossTime + 1.0, workPeriodEnd)
                if idealScoreNow
                else currentIdeal
            ).scoreEvents(endTime=workPeriodEnd)
        ),
    )
