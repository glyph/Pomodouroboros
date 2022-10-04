# -*- test-case-name: pomodouroboros.test_model2 -*-
"""
Model v2.

Spec:

    - https://github.com/glyph/Pomodouroboros/issues/33

What events can occur?

    - time passes, which results in

        - pomodoro progresses

        - pomodoro ends

        - break starts

        - break ends

    - user adds a new intention to the set of available ones

    - user sets an intention from the created set

        - this is different than the current system because expressing an
          intention always results in a new pomodoro (unless one's currently
          running of course)

    - user evaluates their intentionality

3 kinds of intervals

    - pomodoro

    - break

    - grace period

Okay so what is the *alignment* on these grace periods?  Do they begin at the
time when they are originally scheduled to start, or do they start only after
the intention is set?

I think it would make the most sense to have everything aligned up front, so
you can have some visibility into the future, but to have the grace period
itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import (
    ClassVar,
    Generic,
    Iterable,
    Iterator,
    Protocol,
    Sequence,
    TypeVar,
    cast,
)

def debug(*x: object) -> None:
    """
    Emit some messages while debugging.
    """
    if 0:
        print(*x)

class IntervalType(Enum):
    """
    The type of a given interval.
    """

    Pomodoro = "Pomodoro"
    GracePeriod = "GracePeriod"
    Break = "Break"


class PomStartResult(Enum):

    Started = "Started"
    """
    The pomodoro was started, and with it, a new streak was started.
    """

    Continued = "Continued"
    """
    A pomodoro was started, and with it, an existing streak was continued.
    """

    OnBreak = "OnBreak"
    AlreadyStarted = "AlreadyStarted"
    """
    The pomodoro could not be started, either because we were on break, or
    because another pomodoro was already running.
    """


class AnUserInterface(Protocol):
    """
    Protocol that user interfaces must adhere to.
    """

    def intervalStart(self, interval: AnyInterval) -> None:
        """
        Set the interval type to "pomodoro".
        """

    def intervalProgress(self, percentComplete: float) -> None:
        """
        The active interval has progressed to C{percentComplete} percentage
        complete.
        """

    def intervalEnd(self) -> None:
        """
        The interval has ended. Hide the progress bar.
        """

    def intentionAdded(self, intention: Intention) -> None:
        """
        An intention was added to the set of intentions.
        """


class UserInterfaceFactory(Protocol):
    """
    Entry point to a frontend that creates a user interface from a user model
    """

    def __call__(self, model: TheUserModel) -> AnUserInterface:
        ...                     # pragma: no cover


@dataclass
class Pomodoro:
    """
    Interval where the user has set an intention and is attempting to do
    something.
    """

    startTime: float
    intention: Intention
    endTime: float

    intervalType: ClassVar[IntervalType] = IntervalType.Pomodoro

    def scoreEvents(self) -> Iterable[ScoreEvent]:
        yield IntentionScore(self.intention, self.startTime, self.endTime - self.startTime)


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
        return ()


@dataclass
class GracePeriod:
    """
    Interval where the user is taking some time to set the intention before the
    next Pomodoro interval gets started.
    """

    startTime: float
    endTime: float
    intervalType: ClassVar[IntervalType] = IntervalType.GracePeriod
    def scoreEvents(self) -> Iterable[ScoreEvent]:
        return ()


MaybeFloat = TypeVar("MaybeFloat", float, None)


@dataclass
class Estimate:
    """
    An estimation of how long a given task will take, as well as the amount of
    time already spent on it.
    """

    original: float
    """
    The original estimate, in seconds.
    """
    elapsed: float
    """
    The amount of time elapsed on this estimate thus far, in seconds.
    """


@dataclass
class Intention(Generic[MaybeFloat]):
    """
    An intention of something to do.
    """

    description: str
    estimate: Estimate | None


AnyInterval = Pomodoro | Break | GracePeriod
"""
Any interval at all.
"""

AnyRealInterval = Pomodoro | Break
"""
Grace periods aren't 'real' in the sense that they just represent the beginning
of a pomodoro during that time where the its intention is not yet set.  If a
grace period elapses, then it is deleted from history and its pomodoro (and
subsequent pomodoros) don't happen.
"""


class IntentionSuccess(Enum):
    Achieved = "Achieved"
    "The goal described in the intention is finished."
    Focused = "Focused"
    "Good focus during the pomodoro, but the goal was not complete."
    Distracted = "Distracted"
    "Distracted during the pomodoro; not great progress."


class ScoreEvent(Protocol):
    """
    An event that occurred that affected the users score.
    """

    @property
    def points(self) -> int:
        """
        The number of points awarded to this event.
        """

    @property
    def time(self) -> float:
        """
        The point in time where this scoring event occurred.
        """


_is_score_event: type[ScoreEvent]


@dataclass
class IntentionScore:
    """
    Setting an intention gives a point.
    """

    intention: Intention
    time: float
    duration: float
    """
    How long the intention was set for.
    """

    @property
    def points(self) -> int:
        """
        Calculate points based on the duration of the pomodoro.  The idea here
        is that we want later pomodoros to get exponentially more valuable so
        there's an incentive to continue the streak.
        """
        return int((self.duration / 5) ** 2)


_is_score_event = IntentionScore


@dataclass
class EvaluationScore:
    """
    Evaluating an intention gives a point.
    """

    time: float
    points: int = field(default=1, init=False)


_is_score_event = EvaluationScore


@dataclass(frozen=True)
class Duration:
    intervalType: IntervalType
    seconds: float


@dataclass(frozen=True)
class GameRules:
    streakIntervalDurations: Iterable[Duration] = field(
        default_factory=lambda: [
            each
            for pomMinutes, breakMinutes in [
                (5, 5),
                (10, 5),
                (20, 5),
                (30, 10),
            ]
            for each in [
                Duration(IntervalType.Pomodoro, pomMinutes * 60),
                Duration(IntervalType.Break, breakMinutes * 60),
            ]
        ]
    )


@dataclass
class TheUserModel:
    """
    Model of the user's ongoing pomodoro experience.
    """

    _initialTime: float
    _interfaceFactory: UserInterfaceFactory
    _intentions: list[Intention] = field(default_factory=list)
    _currentStreakIntervals: list[AnyInterval] = field(default_factory=list)
    _lastUpdateTime: float = field(init=False)
    _userInterface: AnUserInterface | None = None
    _upcomingDurations: Iterator[Duration] | None = None
    _rules: GameRules = field(default_factory=GameRules)

    _olderStreaks: list[list[AnyInterval]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._lastUpdateTime = 0.0
        self.advanceToTime(self._initialTime)

    def scoreEventsSince(self, timestamp: float) -> Iterable[ScoreEvent]:
        """
        Get all score-relevant events since the given timestamp.
        """
        for streak in [self._currentStreakIntervals, *self._olderStreaks]:
            for interval in streak:
                yield from interval.scoreEvents()

    @property
    def userInterface(self) -> AnUserInterface:
        """
        build the user interface on demand
        """
        if self._userInterface is None:
            self._userInterface = self._interfaceFactory(self)
        return self._userInterface

    @property
    def intentions(self) -> Sequence[Intention]:
        return self._intentions

    def nextInflectionPoint(self) -> float | None:
        """
        Get the next time at which something "interesting" will happen; i.e.
        the time when the current pomodoro will end.

        Sometimes there are no pending interesting events, in which case it
        will return None.
        """
        # TODO: implement

    def advanceToTime(self, newTime: float) -> None:
        """
        Advance to the epoch time given.
        """
        assert newTime >= self._lastUpdateTime
        previousTime, self._lastUpdateTime = self._lastUpdateTime, newTime
        for interval in self._currentStreakIntervals:
            debug("scanning interval", previousTime, newTime, interval)
            if previousTime < interval.startTime:
                debug("previous time before")

                # is there going to be a case where there's a new interval in
                # _currentStreakIntervals, but we have *not* crossed into its range?  I
                # can't think of a case yet
                assert newTime >= interval.startTime

                debug("starting interval")
                self.userInterface.intervalStart(interval)
            if previousTime < interval.endTime:
                current = newTime - interval.startTime
                total = interval.endTime - interval.startTime
                debug("progressing interval", current, total, current / total)
                self.userInterface.intervalProgress(min(1.0, current / total))
            if (previousTime < interval.endTime) and (
                newTime > interval.endTime
            ):
                debug("ending interval")
                self.userInterface.intervalEnd()
                # TODO: enforce that this is the last interval, or that if
                # we've ended one it should be the last one?
                if interval.intervalType == GracePeriod.intervalType:
                    # A grace period expired, so our current streak is now over.
                    self._upcomingDurations = None

                if self._upcomingDurations is not None:
                    nextDuration = next(self._upcomingDurations, None)
                    if nextDuration is None:
                        self._upcomingDurations = None
                    else:
                        startTime = interval.endTime
                        endTime = startTime + nextDuration.seconds
                        newInterval: AnyInterval
                        if nextDuration.intervalType == Pomodoro.intervalType:
                            newInterval = GracePeriod(
                                startTime=startTime, endTime=endTime
                            )
                        if nextDuration.intervalType == Break.intervalType:
                            newInterval = Break(
                                startTime=startTime, endTime=endTime
                            )
                        self._currentStreakIntervals.append(newInterval)

    def addIntention(
        self, description: str, estimation: float | None
    ) -> Intention:
        """
        Add an intention with the given description and time estimate.
        """
        self._intentions.append(
            newIntention := Intention(
                description,
                None
                if estimation is None
                else Estimate(estimation, estimation),
            )
        )
        self.userInterface.intentionAdded(newIntention)
        return newIntention

    def startPomodoro(self, intention: Intention) -> PomStartResult:
        """
        When you start a pomodoro, the length of time set by the pomodoro is
        determined by your current streak so it's not a parameter.
        """
        if self._upcomingDurations is None:
            # TODO: it's already running, implement this case
            # - if a grace period is running then transition to the grace period
            # - if a break is running then refuse
            self._upcomingDurations = iter(self._rules.streakIntervalDurations)
            nextDuration = next(self._upcomingDurations, None)
            assert (
                nextDuration is not None
            ), "empty streak interval durations is invalid"
            assert (
                nextDuration.intervalType == IntervalType.Pomodoro
            ), "streak must begin with a pomodoro"
            newPomodoro = Pomodoro(
                startTime=self._lastUpdateTime,
                endTime=self._lastUpdateTime + nextDuration.seconds,
                intention=intention,
            )
            self._currentStreakIntervals.append(newPomodoro)
            result = PomStartResult.Started

        else:
            assert len(self._currentStreakIntervals) > 0, \
                "If a streak is running, it must have intervals."
            runningIntervalType = self._currentStreakIntervals[-1].intervalType
            if runningIntervalType == Pomodoro.intervalType:
                return PomStartResult.AlreadyStarted
            if runningIntervalType == Break.intervalType:
                return PomStartResult.OnBreak
            # TODO: possibly it would be neater to just dispatch on the literal
            # type of the current running interval.
            gracePeriod: GracePeriod = cast(GracePeriod, self._currentStreakIntervals[-1])
            newPomodoro = self._currentStreakIntervals[-1] = Pomodoro(
                startTime=gracePeriod.startTime,
                endTime=gracePeriod.endTime,
                intention=intention,
            )
            result = PomStartResult.Continued

        self.userInterface.intervalStart(newPomodoro)
        return result

    def evaluatePomodoro(
        self, pomodoro: Pomodoro, success: IntentionSuccess
    ) -> None:
        """
        The user has determined the success criteria.
        """
        # TODO: implement
