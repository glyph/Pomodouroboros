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


class IntervalType(Enum):
    """
    The type of a given interval.
    """

    Pomodoro = "Pomodoro"
    GracePeriod = "GracePeriod"
    Break = "Break"


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
        ...


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


@dataclass
class Break:
    """
    Interval where the user is taking some open-ended time to relax, with no
    specific intention.
    """

    startTime: float
    endTime: float
    intervalType: ClassVar[IntervalType] = IntervalType.Break


@dataclass
class GracePeriod:
    """
    Interval where the user is taking some time to set the intention before the
    next Pomodoro interval gets started.
    """

    startTime: float
    endTime: float
    intervalType: ClassVar[IntervalType] = IntervalType.GracePeriod


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
    points: int = field(default=1, init=False)


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
    _intervals: list[AnyInterval] = field(default_factory=list)
    _score: list[ScoreEvent] = field(default_factory=list)
    _lastUpdateTime: float = field(init=False)
    _userInterface: AnUserInterface | None = None
    _currentStreak: Iterator[Duration] | None = None
    # TODO: rollup of previous intentions / intervals for comparison so we
    # don't need to keep all of history in memory at all times

    _rules: GameRules = GameRules()

    def __post_init__(self) -> None:
        self._lastUpdateTime = 0.0
        self.advanceToTime(self._initialTime)

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
        if newTime < self._lastUpdateTime:
            # Should be impossible?
            return

        previousTime, self._lastUpdateTime = self._lastUpdateTime, newTime
        for interval in self._intervals:
            print("scanning interval", previousTime, newTime, interval)
            if previousTime < interval.startTime:
                print("previous time before")
                if newTime >= interval.startTime:
                    print("starting interval")
                    self.userInterface.intervalStart(interval)
                else:
                    print("not starting")
            if previousTime < interval.endTime:
                current = newTime - interval.startTime
                total = interval.endTime - interval.startTime
                print("progressing interval", current, total, current / total)
                self.userInterface.intervalProgress(min(1.0, current / total))
            if (previousTime < interval.endTime) and (
                newTime > interval.endTime
            ):
                print("ending interval")
                self.userInterface.intervalEnd()
                # TODO: enforce that this is the last interval, or that if
                # we've ended one it should be the last one?
                if interval.intervalType == GracePeriod.intervalType:
                    # A grace period expired, so our current streak is now over.
                    self._currentStreak = None

                if self._currentStreak is not None:
                    nextDuration = next(self._currentStreak, None)
                    if nextDuration is not None:
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
                        self._intervals.append(newInterval)

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

    def startPomodoro(self, intention: Intention) -> None:
        """
        When you start a pomodoro, the length of time set by the pomodoro is
        determined by your current streak so it's not a parameter.
        """
        if self._currentStreak is None:
            # TODO: it's already running, implement this case
            # - if a grace period is running then transition to the grace period
            # - if a break is running then refuse
            self._currentStreak = iter(self._rules.streakIntervalDurations)
            nextDuration = next(self._currentStreak, None)
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
            self._intervals.append(newPomodoro)
        else:
            if self._intervals[-1].intervalType != GracePeriod.intervalType:
                # not allowed. report some kind of error?
                return
            gracePeriod: GracePeriod = cast(GracePeriod, self._intervals[-1])
            newPomodoro = self._intervals[-1] = Pomodoro(
                startTime=gracePeriod.startTime,
                endTime=gracePeriod.endTime,
                intention=intention,
            )
        self.userInterface.intervalStart(newPomodoro)

    def evaluatePomodoro(
        self, pomodoro: Pomodoro, success: IntentionSuccess
    ) -> None:
        """
        The user has determined the success criteria.
        """
        # TODO: implement