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

from copy import deepcopy
from dataclasses import dataclass, field, replace
from enum import Enum
from itertools import count
from typing import (
    Callable,
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


def handleIdleStartPom(
    userModel: TheUserModel, startPom: Callable[[float, float], None]
) -> PomStartResult:
    userModel._upcomingDurations = iter(
        userModel._rules.streakIntervalDurations
    )
    nextDuration = next(userModel._upcomingDurations, None)
    assert (
        nextDuration is not None
    ), "empty streak interval durations is invalid"
    assert (
        nextDuration.intervalType == IntervalType.Pomodoro
    ), "streak must begin with a pomodoro"

    startTime = userModel._lastUpdateTime
    endTime = userModel._lastUpdateTime + nextDuration.seconds

    startPom(startTime, endTime)
    return PomStartResult.Started


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


preludeIntervalMap: dict[IntervalType, type[GracePeriod | Break]] = {
    Pomodoro.intervalType: GracePeriod,
    Break.intervalType: Break,
}


def nextInterval(
    model: TheUserModel,
    timestamp: float,
    previousInterval: AnyInterval | None,
) -> AnyInterval | None:
    """
    Determine what the next interval should be.
    """
    duration = next(model._upcomingDurations, None)
    debug("new duration", duration)
    if duration is not None:
        # We're in an interval. Chain on to the end of it, and start the next
        # duration.
        assert previousInterval is not None, (
            "if we are starting a new duration then we ought "
            "to be coming up on the back of an existing interval"
        )
        newInterval = preludeIntervalMap[duration.intervalType](
            previousInterval.endTime,
            previousInterval.endTime + duration.seconds,
        )
        debug("creating interval", newInterval)
        return newInterval

    # We're not currently in an interval; i.e. we are idling.  If there's a
    # work session active, then let's add a new special interval that tells us
    # about the next point at which we will lose some potential points.
    for start, end in model._sessions:
        if start <= timestamp < end:
            debug("session active", start, end)
            break
    else:
        debug("no session")
        return None

    scoreInfo = idealScore(model, end)
    nextDrop = scoreInfo.nextPointLoss
    debug(nextDrop)
    if nextDrop is None:
        return None
    if nextDrop <= timestamp:
        return None
    debug(f"{timestamp=} {nextDrop=}")
    return StartPrompt(timestamp, nextDrop, scoreInfo.pointsLost())


def idealFuture(
    model: TheUserModel, activityStart: float, workPeriodEnd: float
) -> TheUserModel:
    """
    Compute the ideal score if we were to maintain focus through the end of
    the given time period.

    @param activityStart: The point at which the user begins taking their
        next action to complete ideal future streaks.

    @param workPeriodEnd: The point beyond which we will not count points
        any more; i.e. the end of the work day.
    """
    previouslyUpcoming = list(model._upcomingDurations)

    def split() -> Iterator[Duration]:
        return iter(previouslyUpcoming)

    model._upcomingDurations = split()
    hypothetical = deepcopy(
        replace(
            model,
            # TODO: intentions are mutable! we need to *deep*-clone this object,
            # otherwise our hypothetical evaluations will actually complete
            # existing intentions.
            _intentions=model._intentions[:],
            _interfaceFactory=lambda whatever: NoUserInterface(),
            _userInterface=NoUserInterface(),
            _upcomingDurations=split(),
            _sessions=[],
            # TODO: intervals (specifically: pomodoros) are also mutable.
            _allStreaks=[each[:] for each in model._allStreaks],
        )
    )
    # because it's init=False we have to copy it manually
    hypothetical._lastUpdateTime = model._lastUpdateTime

    debug("advancing to activity start", model._lastUpdateTime, activityStart)
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
        workingInterval = hypothetical._activeInterval
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


def idealScore(model: TheUserModel, workPeriodEnd: float) -> IdealScoreInfo:
    """
    Compute the inflection point for the ideal score the user might
    achieve.  We present two hypothetical futures: one where the user
    executes perfectly, and the other where they wait long enough to lose
    some element of that perfect score, and then begins executing
    perfectly.
    """
    debug("ideal future 1")
    workPeriodBegin = model._lastUpdateTime
    currentIdeal = idealFuture(model, workPeriodBegin, workPeriodEnd)
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
        now=model._lastUpdateTime,
        idealScoreNow=idealScoreNow,
        workPeriodEnd=workPeriodEnd,
        nextPointLoss=pointLossTime,
        idealScoreNext=list(
            (
                idealFuture(model, pointLossTime + 1.0, workPeriodEnd)
                if idealScoreNow
                else currentIdeal
            ).scoreEvents(endTime=workPeriodEnd)
        ),
    )


@dataclass
class TheUserModel:
    """
    Model of the user's ongoing pomodoro experience.
    """

    _initialTime: float
    _interfaceFactory: UserInterfaceFactory
    _intentions: list[Intention] = field(default_factory=list)
    _activeInterval: AnyInterval | None = None
    """
    The list of active streak intervals currently being worked on.
    """

    _lastUpdateTime: float = field(init=False, default=0.0)
    _userInterface: AnUserInterface | None = None
    _upcomingDurations: Iterator[Duration] = iter(())
    _rules: GameRules = field(default_factory=GameRules)

    _allStreaks: list[list[AnyInterval]] = field(default_factory=lambda: [[]])
    """
    The list of previous streaks, each one being a list of its intervals, that
    are now completed.
    """
    _sessions: list[tuple[float, float]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self._initialTime > self._lastUpdateTime:
            self.advanceToTime(self._initialTime)

    def scoreEvents(
        self, *, startTime: float | None = None, endTime: float | None = None
    ) -> Iterable[ScoreEvent]:
        """
        Get all score-relevant events since the given timestamp.
        """
        if startTime is None:
            startTime = self._initialTime
        if endTime is None:
            endTime = self._lastUpdateTime
        for intentionIndex, intention in enumerate(self._intentions):
            for event in intention.intentionScoreEvents(intentionIndex):
                if event.time <= endTime:
                    yield event
        for streak in self._allStreaks:
            for interval in streak:
                if interval.startTime > startTime:
                    for event in interval.scoreEvents():
                        debug(
                            "score", event.time > endTime, event, event.points
                        )
                        if event.time <= endTime:
                            yield event

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

    @property
    def availableIntentions(self) -> Sequence[Intention]:
        """
        This property is a list of all intentions that are available for the
        user to select for a new pomodoro.
        """
        return [
            i for i in self._intentions if not i.completed and not i.abandoned
        ]

    def _makeNextInterval(self, newTime: float) -> None:
        """
        Create the next interval.
        """
        new = self._activeInterval = nextInterval(
            self, newTime, self._activeInterval
        )
        if new is not None:
            self._allStreaks[-1].append(new)
            self.userInterface.intervalStart(new)

    def advanceToTime(self, newTime: float) -> None:
        """
        Advance to the epoch time given.
        """
        assert (
            newTime >= self._lastUpdateTime
        ), f"Time cannot move backwards; past={newTime} < present={self._lastUpdateTime}"
        debug("advancing to", newTime, "from", self._lastUpdateTime)
        previousTime, self._lastUpdateTime = self._lastUpdateTime, newTime
        previousInterval: AnyInterval | None = None
        if self._activeInterval is None:
            # bootstrap our initial interval (specifically, this is where
            # StartPrompt gets kicked off in an otherwise idle session)
            self._makeNextInterval(newTime)
        while ((interval := self._activeInterval) is not None) and (
            interval != previousInterval
        ):
            previousInterval = interval
            current = newTime - interval.startTime
            total = interval.endTime - interval.startTime
            debug("progressing interval", current, total, current / total)
            self.userInterface.intervalProgress(min(1.0, current / total))
            if newTime >= interval.endTime:
                debug("ending interval")
                self.userInterface.intervalEnd()
                if interval.intervalType == GracePeriod.intervalType:
                    # A grace period expired, so our current streak is now
                    # over, regardless of whether new intervals might be
                    # produced for some reason.
                    self._upcomingDurations = iter(())
                    # When a grace period expires, a streak is broken, so we
                    # make a new one.
                    self._allStreaks.append([])
                self._makeNextInterval(newTime)

        # If there's an active streak, we definitionally should not have
        # advanced past its end.
        assert (
            self._activeInterval is None
            or self._lastUpdateTime <= self._activeInterval.endTime
        ), (
            "Active interval should be in the present, not the past; "
            f"present={self._lastUpdateTime} "
            f"end={self._activeInterval.endTime}"
        )

    def addIntention(
        self, description: str, estimatedDuration: float | None
    ) -> Intention:
        """
        Add an intention with the given description and time estimate.
        """
        self._intentions.append(
            newIntention := Intention(self._lastUpdateTime, description)
        )
        if estimatedDuration is not None:
            newIntention.estimates.append(
                Estimate(
                    duration=estimatedDuration, madeAt=self._lastUpdateTime
                )
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
        handleStartFunc = (
            handleIdleStartPom
            if self._activeInterval is None
            else self._activeInterval.handleStartPom
        )

        def startPom(startTime: float, endTime: float) -> None:
            newPomodoro = Pomodoro(
                intention=intention,
                indexInStreak=sum(
                    isinstance(each, Pomodoro) for each in self._allStreaks[-1]
                ),
                startTime=startTime,
                endTime=endTime,
            )
            intention.pomodoros.append(newPomodoro)
            self._activeInterval = newPomodoro
            self._allStreaks[-1].append(newPomodoro)
            self.userInterface.intervalStart(newPomodoro)

        return handleStartFunc(self, startPom)

    def evaluatePomodoro(
        self, pomodoro: Pomodoro, result: EvaluationResult
    ) -> None:
        """
        The user has determined the success criteria.
        """
        timestamp = self._lastUpdateTime
        pomodoro.evaluation = Evaluation(result, timestamp)
        if result == EvaluationResult.achieved:
            assert (
                pomodoro.intention.completed
            ), "evaluation was set, should be complete"
            self.userInterface.intentionCompleted(pomodoro.intention)
            if timestamp < pomodoro.endTime:
                # We evaluated the pomodoro as *complete* early, which is a
                # special case.  Evaluating it in other ways allows it to
                # continue.  (Might want an 'are you sure' in the UI for this,
                # since other evaluations can be reversed.)
                assert pomodoro is self._activeInterval
                pomodoro.endTime = timestamp
                # We now need to advance back to the current time since we've
                # changed the landscape; there's a new interval that now starts
                # there, and we need to emit our final progress notification
                # and build that new interval.
                self.advanceToTime(self._lastUpdateTime)
