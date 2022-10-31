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

from dataclasses import dataclass, field, replace
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
    StartPrompt = "StartPrompt"


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


@dataclass
class NoUserInterface(AnUserInterface):
    """
    Do-nothing implementation of a user interface.
    """


class UserInterfaceFactory(Protocol):
    """
    Entry point to a frontend that creates a user interface from a user model
    """

    def __call__(self, model: TheUserModel) -> AnUserInterface:
        ...  # pragma: no cover


class EvaluationResult(Enum):
    """
    How did a given Pomodoro go?
    """

    distracted = "distracted"
    """
    The user was distracted by something that they could have had control over,
    and ideally would have ignored or noted for later.
    """

    interrupted = "interrupted"
    """
    The user was interrupted by something that was legitimately higher priority
    than their specified intention.
    """

    focused = "focused"
    """
    The user was focused on the task at hand.
    """

    achieved = "achieved"
    """
    The intended goal of the pomodoro was achieved.
    """


@dataclass
class Evaluation:
    """
    A decision by the user about the successfulness of the intention associated
    with a pomodoro.
    """

    result: EvaluationResult
    timestamp: float


@dataclass
class Pomodoro:
    """
    Interval where the user has set an intention and is attempting to do
    something.
    """

    startTime: float
    intention: Intention
    endTime: float

    evaluation: Evaluation | None = None

    intervalType: ClassVar[IntervalType] = IntervalType.Pomodoro

    def scoreEvents(self) -> Iterable[ScoreEvent]:
        yield IntentionScore(
            self.intention, self.startTime, self.endTime - self.startTime
        )

    def evaluate(self, result: EvaluationResult, timestamp: float) -> None:
        """
        Evaluate the completion of this pomodoro.

        Open questions:

            - should there be a time limit on performing this evaluation?

                - should evaluating after a certain amount of time be
                  disallowed completely, or merely discouraged by a score
                  reduction?

            - should you be able to go backwards to "not evaluated at all"?

            - should we have a discrete Evaluation object
        """
        self.evaluation = Evaluation(result, timestamp)


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
class Intention(Generic[MaybeFloat]):
    """
    An intention of something to do.
    """

    description: str
    estimate: float | None
    pomodoros: list[Pomodoro] = field(default_factory=list)


@dataclass
class StartPrompt:
    """
    Interval where the user is not currently in a streak, and we are prompting
    them to get started.
    """

    startTime: float
    endTime: float
    pointsLost: int

    intervalType: ClassVar[IntervalType] = IntervalType.StartPrompt

    def scoreEvents(self) -> Iterable[ScoreEvent]:
        return ()


AnyInterval = Pomodoro | Break | GracePeriod | StartPrompt
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
        return int((self.duration / (5 * 60)) ** 2)


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
class IdealScoreInfo:
    """
    Information about time remaining to the next ideal score loss.
    """

    now: float
    workPeriodEnd: float
    idealScoreNow: list[ScoreEvent]
    nextPointLoss: float | None
    idealScoreNext: list[ScoreEvent]

    def pointsLost(self) -> int:
        """
        Compute, numerically, how many points will be lost at L{self.nextPointLoss}.
        """
        return sum(each.points for each in self.idealScoreNow) - sum(
            each.points for each in self.idealScoreNext
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
    """
    The list of active streak intervals currently being worked on.
    """

    _lastUpdateTime: float = field(init=False, default=0.0)
    _userInterface: AnUserInterface | None = None
    _upcomingDurations: Iterator[Duration] | None = None
    _rules: GameRules = field(default_factory=GameRules)

    _olderStreaks: list[list[AnyInterval]] = field(default_factory=list)
    """
    The list of previous streaks, each one being a list of its intervals, that
    are now completed.
    """
    _sessions: list[tuple[float, float]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self._initialTime > self._lastUpdateTime:
            self.advanceToTime(self._initialTime)

    def idealFuture(
        self, activityStart: float, workPeriodEnd: float
    ) -> TheUserModel:
        """
        Compute the ideal score if we were to maintain focus through the end of
        the given time period.

        @param activityStart: The point at which the user begins taking their
            next action to complete ideal future streaks.

        @param workPeriodEnd: The point beyond which we will not count points
            any more; i.e. the end of the work day.
        """
        upcomingDurations = (
            list(self._upcomingDurations)
            if self._upcomingDurations is not None
            else None
        )

        def split() -> Iterator[Duration] | None:
            return (
                iter(upcomingDurations)
                if upcomingDurations is not None
                else None
            )

        self._upcomingDurations = split()
        hypothetical = replace(
            self,
            _intentions=self._intentions[:],
            _interfaceFactory=lambda whatever: NoUserInterface(),
            _currentStreakIntervals=self._currentStreakIntervals[:],
            _userInterface=NoUserInterface(),
            _upcomingDurations=split(),
            _sessions=[],
        )
        # because it's init=False we have to copy it manually
        hypothetical._lastUpdateTime = self._lastUpdateTime

        debug(
            "advancing to activity start", self._lastUpdateTime, activityStart
        )
        hypothetical.advanceToTime(activityStart)

        while hypothetical._lastUpdateTime <= workPeriodEnd:
            if hypothetical._currentStreakIntervals:
                interval = hypothetical._currentStreakIntervals[-1]
                debug("advancing to interval end")
                hypothetical.advanceToTime(interval.endTime + 1)
                if isinstance(interval, Pomodoro):
                    hypothetical.evaluatePomodoro(
                        interval, EvaluationResult.achieved
                    )
                # TODO: when estimation gets a score, make sure to put one that
                # is exactly correct here.
            if (not hypothetical._currentStreakIntervals) or isinstance(
                hypothetical._currentStreakIntervals[-1], GracePeriod
            ):
                intention = hypothetical.addIntention("placeholder", None)
                startResult = hypothetical.startPomodoro(intention)
                assert startResult in {
                    PomStartResult.Started,
                    PomStartResult.Continued,
                }, "invariant failed: could not actually start pomodoro"
        return hypothetical

    def idealScore(self, workPeriodEnd: float) -> IdealScoreInfo:
        """
        Compute the inflection point for the ideal score the user might
        achieve.  We present two hypothetical futures: one where the user
        executes perfectly, and the other where they wait long enough to lose
        some element of that perfect score, and then begins executing
        perfectly.
        """
        debug("ideal future 1")
        currentIdeal = self.idealFuture(self._lastUpdateTime, workPeriodEnd)

        def scoreFilter(model: TheUserModel) -> Iterable[ScoreEvent]:
            for each in model.scoreEventsSince(model._initialTime):
                if each.time >= workPeriodEnd:
                    break
                yield each

        idealScoreNow = list(scoreFilter(currentIdeal))
        if not idealScoreNow:
            return IdealScoreInfo(
                now=self._lastUpdateTime,
                idealScoreNow=idealScoreNow,
                workPeriodEnd=workPeriodEnd,
                nextPointLoss=None,
                idealScoreNext=idealScoreNow,
            )
        pointLossTime = idealScoreNow[-1].time
        debug("ideal future 2")
        futureIdeal = (
            self.idealFuture(pointLossTime, workPeriodEnd)
            if idealScoreNow
            else currentIdeal
        )
        idealScoreNext = list(scoreFilter(futureIdeal))
        return IdealScoreInfo(
            now=self._lastUpdateTime,
            idealScoreNow=idealScoreNow,
            workPeriodEnd=workPeriodEnd,
            nextPointLoss=pointLossTime,
            idealScoreNext=idealScoreNext,
        )

    def scoreEventsSince(self, timestamp: float) -> Iterable[ScoreEvent]:
        """
        Get all score-relevant events since the given timestamp.
        """
        for streak in [*self._olderStreaks, self._currentStreakIntervals]:
            for interval in streak:
                if interval.startTime > timestamp:
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

    def advanceToTime(self, newTime: float) -> None:
        """
        Advance to the epoch time given.
        """
        assert (
            newTime >= self._lastUpdateTime
        ), f"{newTime} < {self._lastUpdateTime}"
        debug("advancing to", newTime, "from", self._lastUpdateTime)
        previousTime, self._lastUpdateTime = self._lastUpdateTime, newTime
        currentInterval: AnyInterval | None = None
        for interval in self._currentStreakIntervals:
            debug("scanning interval", previousTime, newTime, interval)
            if previousTime < interval.startTime:
                debug("previous time before")

                # is there going to be a case where there's a new interval in
                # _currentStreakIntervals, but we have *not* crossed into its range?  I
                # can't think of a case yet
                assert (
                    newTime >= interval.startTime
                ), f"{previousTime} {newTime} {interval.startTime} {self._currentStreakIntervals}"
                debug("starting interval")
                self.userInterface.intervalStart(interval)
            if previousTime < interval.endTime:
                current = newTime - interval.startTime
                total = interval.endTime - interval.startTime
                debug("progressing interval", current, total, current / total)
                self.userInterface.intervalProgress(min(1.0, current / total))
                currentInterval = interval
            if (previousTime < interval.endTime) and (
                newTime > interval.endTime
            ):
                debug("ending interval")
                self.userInterface.intervalEnd()
                currentInterval = None
                # TODO: enforce that this is the last interval, or that if
                # we've ended one it should be the last one?
                if interval.intervalType == GracePeriod.intervalType:
                    # A grace period expired, so our current streak is now
                    # over, regardless of whether new intervals might be
                    # produced.
                    self._upcomingDurations = None

                if self._upcomingDurations is not None:
                    nextDuration = next(self._upcomingDurations, None)
                    if nextDuration is None:
                        self._upcomingDurations = None
                else:
                    nextDuration = None

                if nextDuration is None:
                    old, self._currentStreakIntervals[:] = (
                        self._currentStreakIntervals[:],
                        (),
                    )
                    self._olderStreaks.append(old)
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
                    # currentInterval = newInterval # ?

        if currentInterval is None:
            # We're not currently in an interval; i.e. we are idling.  If
            # there's a work session active, then let's add a new special
            # interval that tells us about the next point at which we will lose
            # some potential points.
            newSession = None
            for (eachStart, eachEnd) in self._sessions:
                if eachStart <= newTime < eachEnd:
                    newSession = (eachStart, eachEnd)
                    break
            if newSession is not None:
                sessionStart, sessionEnd = newSession
                scoreInfo = self.idealScore(sessionEnd)
                nextDrop = scoreInfo.nextPointLoss
                if nextDrop is not None:
                    newInterval = StartPrompt(
                        newTime, nextDrop, scoreInfo.pointsLost()
                    )
                    self._currentStreakIntervals.append(newInterval)
                    self.userInterface.intervalStart(newInterval)
        if self._currentStreakIntervals:
            # If there's an active streak, we definitionally should not have
            # advanced past its end.
            assert (
                self._lastUpdateTime
                <= self._currentStreakIntervals[-1].endTime
            ), f"{self._upcomingDurations} {self._lastUpdateTime} {self._currentStreakIntervals[-1].endTime}"

    def addIntention(
        self, description: str, estimation: float | None
    ) -> Intention:
        """
        Add an intention with the given description and time estimate.
        """
        self._intentions.append(
            newIntention := Intention(description, estimation)
        )
        self.userInterface.intentionAdded(newIntention)
        return newIntention

    def addSession(self, startTime: float, endTime: float) -> None:
        """
        Add a 'work session'; a discrete interval where we will be scored, and
        notified of potential drops to our score if we don't set intentions.
        """
        self._sessions.append((startTime, endTime))
        self._sessions.sort()

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
            assert (
                len(self._currentStreakIntervals) > 0
            ), "If a streak is running, it must have intervals."
            runningIntervalType = self._currentStreakIntervals[-1].intervalType
            if runningIntervalType == Pomodoro.intervalType:
                return PomStartResult.AlreadyStarted
            if runningIntervalType == Break.intervalType:
                return PomStartResult.OnBreak
            # TODO: possibly it would be neater to just dispatch on the literal
            # type of the current running interval.
            assert runningIntervalType in {
                GracePeriod.intervalType,
                StartPrompt.intervalType,  # TODO this value is not tested
            }
            gracePeriodOrStartPrompt = self._currentStreakIntervals[-1]
            newPomodoro = self._currentStreakIntervals[-1] = Pomodoro(
                startTime=gracePeriodOrStartPrompt.startTime,
                endTime=gracePeriodOrStartPrompt.endTime,
                intention=intention,
            )
            result = PomStartResult.Continued

        intention.pomodoros.append(newPomodoro)
        self.userInterface.intervalStart(newPomodoro)
        return result

    def evaluatePomodoro(
        self, pomodoro: Pomodoro, result: EvaluationResult
    ) -> None:
        """
        The user has determined the success criteria.
        """
        pomodoro.evaluate(result, self._lastUpdateTime)
