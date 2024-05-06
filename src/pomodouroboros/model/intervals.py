from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, ClassVar, Iterable

from .boundaries import (
    EvaluationResult,
    IntervalType,
    PomStartResult,
    ScoreEvent,
)
from .intention import Intention
from .scoring import BreakCompleted, EvaluationScore, IntentionSet

if TYPE_CHECKING:
    from .nexus import Nexus


@dataclass(frozen=True)
class Duration:
    """
    A duration describes the amount of time that a 'real' interval (i.e. either
    break or pomodoro) that will be generated in a continuing streak.
    """

    intervalType: IntervalType
    seconds: float


@dataclass
class Evaluation:
    """
    A decision by the user about the successfulness of the intention associated
    with a pomodoro.
    """

    result: EvaluationResult
    timestamp: float

    def scoreEvents(self) -> Iterable[ScoreEvent]:
        yield EvaluationScore(self.timestamp, self.result.points)


@dataclass
class Break:
    """
    Interval where the user is taking some open-ended time to relax, with no
    specific intention.
    """

    startTime: float
    endTime: float
    intervalType: ClassVar[IntervalType] = IntervalType.Break

    def scoreEvents(self) -> Iterable[ScoreEvent]:
        return [BreakCompleted(self)]

    def handleStartPom(
        self, nexus: Nexus, startPom: Callable[[float, float], None]
    ) -> PomStartResult:
        return PomStartResult.OnBreak


@dataclass
class Pomodoro:
    """
    Interval where the user has set an intention and is attempting to do
    something.
    """

    startTime: float
    intention: Intention
    endTime: float
    indexInStreak: int

    evaluation: Evaluation | None = None
    intervalType: ClassVar[IntervalType] = IntervalType.Pomodoro

    def handleStartPom(
        self, nexus: Nexus, startPom: Callable[[float, float], None]
    ) -> PomStartResult:
        return PomStartResult.AlreadyStarted

    def scoreEvents(self) -> Iterable[ScoreEvent]:
        yield IntentionSet(
            intention=self.intention,
            time=self.startTime,
            duration=self.endTime - self.startTime,
            streakLength=self.indexInStreak,
        )
        if self.evaluation is not None:
            yield from self.evaluation.scoreEvents()


@dataclass
class GracePeriod:
    """
    Interval where the user is taking some time to set the intention before the
    next Pomodoro interval gets started.
    """

    startTime: float
    originalPomEnd: float
    intervalType: ClassVar[IntervalType] = IntervalType.GracePeriod

    @property
    def endTime(self) -> float:
        """
        Compute the end time from the grace period.
        """
        return self.startTime + ((self.originalPomEnd - self.startTime) / 3)

    def scoreEvents(self) -> Iterable[ScoreEvent]:
        return ()

    def handleStartPom(
        self, nexus: Nexus, startPom: Callable[[float, float], None]
    ) -> PomStartResult:
        # if it's a grace period then we're going to replace it, same start
        # time, same original end time (the grace period itself may be
        # shorter)
        startPom(self.startTime, self.originalPomEnd)
        return PomStartResult.Continued


@dataclass
class StartPrompt:
    """
    Interval where the user is not currently in a streak, and we are prompting
    them to get started.
    """

    startTime: float
    endTime: float
    pointsBeforeLoss: float
    pointsAfterLoss: float

    intervalType: ClassVar[IntervalType] = IntervalType.StartPrompt

    @property
    def pointsLost(self) -> float:
        """
        Convenience attribute to compute the number of points that will be
        lost.
        """
        return self.pointsBeforeLoss - self.pointsAfterLoss

    def scoreEvents(self) -> Iterable[ScoreEvent]:
        return ()

    def handleStartPom(
        self, nexus: Nexus, startPom: Callable[[float, float], None]
    ) -> PomStartResult:
        nexus.userInterface.intervalProgress(1.0)
        nexus.userInterface.intervalEnd()
        return handleIdleStartPom(nexus, startPom)

@dataclass
class Idle:
    startTime: float
    endTime: float
    intervalType: ClassVar[IntervalType] = IntervalType.Idle

    def scoreEvents(self) -> Iterable[ScoreEvent]:
        return ()

    def handleStartPom(
        self, nexus: Nexus, startPom: Callable[[float, float], None]
    ) -> PomStartResult:
        nexus.userInterface.intervalProgress(1.0)
        nexus.userInterface.intervalEnd()
        return handleIdleStartPom(nexus, startPom)

AnyStreakInterval = Pomodoro | Break | GracePeriod | StartPrompt
"""
Any interval that can occur in a streak.
"""
AnyIntervalOrIdle = AnyStreakInterval | Idle
"""
Any interval at all.
"""

AnyRealInterval = Pomodoro | Break
"""
'Real' intervals are those which persist as a historical record past the end of
their elapsed time.  Grace periods and start prompts are temporary placeholders
which are replaced by a started pomodoro once it gets going; start prompts are
just removed and grace periods are clipped out in-place with the start of the
pomodoro going back to their genesis.
"""


def handleIdleStartPom(
    nexus: Nexus, startPom: Callable[[float, float], None]
) -> PomStartResult:
    nexus._upcomingDurations = iter(nexus._rules.streakIntervalDurations)
    nextDuration = next(nexus._upcomingDurations, None)
    assert (
        nextDuration is not None
    ), "empty streak interval durations is invalid"
    assert (
        nextDuration.intervalType == IntervalType.Pomodoro
    ), "streak must begin with a pomodoro"

    startTime = nexus._lastUpdateTime
    endTime = nexus._lastUpdateTime + nextDuration.seconds

    startPom(startTime, endTime)
    return PomStartResult.Started
