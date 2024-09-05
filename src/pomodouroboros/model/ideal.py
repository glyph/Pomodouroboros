# -*- test-case-name: pomodouroboros.model.test.test_model -*-
from __future__ import annotations

from dataclasses import dataclass
from itertools import count
from typing import TYPE_CHECKING, Sequence

from .boundaries import EvaluationResult, PomStartResult, ScoreEvent
from .debugger import debug
from .intervals import AnyIntervalOrIdle, Break, GracePeriod, Pomodoro, Idle

if TYPE_CHECKING:
    from .nexus import Nexus
    from .intention import Intention


@dataclass
class ScoreSummary:
    """
    A L{ScoreSummary} is a container for L{ScoreEvent}s that can summarize
    things about them.
    """

    events: Sequence[ScoreEvent]

    @property
    def totalScore(self) -> float:
        """
        Compute the total score for the contained scores.
        """
        return sum(each.points for each in self.events)


@dataclass
class IdealScoreInfo:
    """
    Information about time remaining to the next ideal score loss.
    """

    now: float
    sessionStart: float
    sessionEnd: float
    idealScoreNow: ScoreSummary
    nextPointLoss: float | None
    idealScoreNext: ScoreSummary

    def scoreBeforeLoss(self) -> float:
        """
        If the user executes with perfect focus from L{now
        <IdealScoreInfo.now>} to L{the end of their current session
        <IdealScoreInfo.sessionEnd>}, before the next loss in ideal score
        occurs at L{nextPointLoss <IdealScoreInfo.nextPointLoss>}?
        """
        return self.idealScoreNow.totalScore

    def scoreAfterLoss(self) -> float:
        """
        What would the ideal score be after the next loss occurs at
        C{nextPointLoss}?
        """
        return self.idealScoreNext.totalScore

    def pointsLost(self) -> float:
        """
        Mostly just for testing convenience right now.
        """
        return self.scoreBeforeLoss() - self.scoreAfterLoss()


def idealFuture(
    nexus: Nexus, activityStart: float, sessionEnd: float
) -> Nexus:
    """
    Compute the ideal score if we were to maintain focus through the end of
    the given time period.

    @param activityStart: The point at which the user begins taking their
        next action to complete ideal future streaks.

    @param sessionEnd: The point beyond which we will not count points
        any more; i.e. the end of the work day.
    """
    hypothetical = nexus.cloneWithoutUI()
    debug("advancing to activity start", nexus._lastUpdateTime, activityStart)
    hypothetical.advanceToTime(activityStart)

    c = count()

    def newPlaceholder() -> Intention:
        return hypothetical.addIntention(f"placeholder {next(c)}")

    fillerIntentions = [
        newPlaceholder()
        for _ in range(max(0, 9 - len(hypothetical.intentions)))
    ]
    # fillerIntentions: list[Intention] = []

    def availablePlaceholder() -> Intention:
        if fillerIntentions:
            return fillerIntentions.pop(0)
        return newPlaceholder()

    while hypothetical._lastUpdateTime <= sessionEnd:
        workingInterval: AnyIntervalOrIdle = hypothetical._activeInterval
        debug("ideal working interval:", workingInterval)
        if isinstance(workingInterval, (Idle, GracePeriod)):
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


def idealScore(
    nexus: Nexus, sessionStart: float, sessionEnd: float
) -> IdealScoreInfo:
    """
    Compute the inflection point for the ideal score the user might achieve.
    We present two hypothetical futures: one where the user executes perfectly
    from the current update time of the given C{Nexus} to C{sessionEnd}, and
    the other where they wait exactly long enough to lose I{one} element of
    that perfect score, and then begin executing perfectly.
    """
    debug("ideal future 1")
    workPeriodBegin = nexus._lastUpdateTime
    currentIdeal = idealFuture(nexus, workPeriodBegin, sessionEnd)
    idealScoreNow = sorted(
        # TODO: we're scoring all events from all time here
        currentIdeal.scoreEvents(startTime=sessionStart, endTime=sessionEnd),
        key=lambda it: it.time,
    )
    if not idealScoreNow:
        return IdealScoreInfo(
            now=workPeriodBegin,
            idealScoreNow=ScoreSummary(idealScoreNow),
            sessionStart=sessionStart,
            sessionEnd=sessionEnd,
            nextPointLoss=None,
            idealScoreNext=ScoreSummary(idealScoreNow),
        )
    latestScoreTime = idealScoreNow[-1].time
    pointLossTime = workPeriodBegin + (sessionEnd - latestScoreTime)
    return IdealScoreInfo(
        now=nexus._lastUpdateTime,
        idealScoreNow=ScoreSummary(idealScoreNow),
        sessionStart=sessionStart,
        sessionEnd=sessionEnd,
        nextPointLoss=pointLossTime,
        idealScoreNext=ScoreSummary(
            list(
                (
                    idealFuture(nexus, pointLossTime + 1.0, sessionEnd)
                    if idealScoreNow
                    else currentIdeal
                ).scoreEvents(startTime=sessionStart, endTime=sessionEnd)
            )
        ),
    )
