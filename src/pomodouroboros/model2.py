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

    def intentionAbandoned(self, intention: Intention) -> None:
        """
        An intention was removed from the set of intentions by the user.
        """

    def intentionCompleted(self, intention: Intention) -> None:
        """
        An intention was marked as completed, so it is no longer available for
        selection for new pomodoros by the user.
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

    points: float

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


EvaluationResult.distracted.points = 0.1
EvaluationResult.interrupted.points = 0.2
EvaluationResult.focused.points = 1.0
EvaluationResult.achieved.points = 1.25


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
        self, userModel: TheUserModel, startPom: Callable[[float, float], None]
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

    def handleStartPom(
        self, userModel: TheUserModel, startPom: Callable[[float, float], None]
    ) -> PomStartResult:
        return PomStartResult.OnBreak


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
        self, userModel: TheUserModel, startPom: Callable[[float, float], None]
    ) -> PomStartResult:
        # if it's a grace period then we're going to replace it, same start
        # time, same original end time (the grace period itself may be
        # shorter)
        startPom(self.startTime, self.originalPomEnd)
        return PomStartResult.Continued


@dataclass
class Estimate:
    """
    A guess was made about how long an L{Intention} would take to complete.
    """

    duration: float  # how long do we think the thing is going to take?
    madeAt: float  # when was this estimate made?


@dataclass
class Intention:
    """
    An intention of something to do.
    """

    created: float
    description: str
    estimates: list[Estimate] = field(default_factory=list)
    pomodoros: list[Pomodoro] = field(default_factory=list)
    abandoned: bool = False

    @property
    def completed(self) -> bool:
        """
        Has this intention been completed?
        """
        return (
            False
            if not self.pomodoros
            else (evaluation := self.pomodoros[-1].evaluation) is not None
            and evaluation.result == EvaluationResult.achieved
        )

    def scoreEvents(self) -> Iterable[ScoreEvent]:
        # If we've ever been used in a pomodoro even once, the user gets a
        # point for creating this intention.
        if self.pomodoros:
            yield IntentionCreatedEvent(self)
        for estimate, _ in zip(self.estimates, range(len(self.pomodoros) + 1)):
            # Only give a point for one estimation per attempt; estimating is
            # good, but correcting more than once per work session is just
            # faffing around
            yield AttemptedEstimation(estimate)
        if self.completed:
            yield IntentionCompleted(self)
            if self.estimates:
                yield EstimationAccuracy(self)


class ScoreEvent(Protocol):
    """
    An event that occurred that affected the users score.
    """

    @property
    def points(self) -> float:
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
class IntentionCreatedEvent:
    """
    An intention was created (and used at least once in a pomodoro).
    """

    intention: Intention

    @property
    def time(self) -> float:
        return self.intention.created

    @property
    def points(self) -> int:
        """
        Creating an intention (and then using it) always only gives a single
        point.  Creating intentions is good and it's good to use them.
        """
        return 1


_is_score_event = IntentionCreatedEvent

@dataclass
class IntentionCompleted:
    intention: Intention

    @property
    def time(self) -> float:
        evaluation = self.intention.pomodoros[-1].evaluation
        assert evaluation is not None
        return evaluation.timestamp

    @property
    def points(self) -> int:
        """
        When an intention is completed, the user is given 10 points.  This can
        be given two additional bonuses: if it took more than 1 pomodoro to
        finish, 1 additional point per pomodoro will be granted, up to 5 pomodoros.
        """
        score = 10
        score += min(5, (len(self.intention.pomodoros) - 1))
        return score


_is_score_event = IntentionCompleted
@dataclass
class EstimationAccuracy:
    intention: Intention

    @property
    def time(self) -> float:
        evaluation = self.intention.pomodoros[-1].evaluation
        assert evaluation is not None
        return evaluation.timestamp

    @property
    def points(self) -> int:
        """
        When an intention is completed, give some points for how close the
        estimate was.
        """
        actualTimeTaken = sum((each.endTime-each.startTime) for each in self.intention.pomodoros)
        timeOfEvaluation = self.time
        allEstimateScores: list[int] = []
        for estimate, recencyCap in zip(self.intention.estimates[-10::-1], range(10, 1, -1)):
            # Counting down from the most recent estimate to the 10th most
            # recent, we give progressively smaller caps to the estimate.
            timeSinceEstimate = timeOfEvaluation - estimate.madeAt
            # You get more points for estimates that are earlier (specifically,
            # you only get max credit for estimates that are made longer ago
            # than the total time that the thing took to do).  This is a rough
            # heuristic, because it's still technically gameable if you have a
            # task that takes a super long time and you have dozens of
            # pomodoros on it, estimate that you only have a single pomdoro
            # left, then wait a day before completing it.
            timeSinceEstimateCap = int(min(1.0, timeSinceEstimate / actualTimeTaken) * 10)
            # You obviously get more points for having made more accurate estimates.
            distanceSeconds = abs(actualTimeTaken - estimate.duration)
            distanceHours = distanceSeconds / (60*60)
            # within 100 hours you can get 10 points, within 90 hours you can
            # get 9, etc
            distanceScore = min(10, int(distanceHours / 10))
            allEstimateScores.append(min([distanceScore, timeSinceEstimateCap, recencyCap]))
        return max(allEstimateScores)

_is_score_event=EstimationAccuracy
@dataclass
class AttemptedEstimation:
    """
    The user attempted to estimate how long this would take.
    """

    estimate: Estimate

    @property
    def time(self) -> float:
        return self.estimate.madeAt

    @property
    def points(self) -> int:
        return 1


@dataclass
class StartPrompt:
    """
    Interval where the user is not currently in a streak, and we are prompting
    them to get started.
    """

    startTime: float
    endTime: float
    pointsLost: float

    intervalType: ClassVar[IntervalType] = IntervalType.StartPrompt

    def scoreEvents(self) -> Iterable[ScoreEvent]:
        return ()

    def handleStartPom(
        self, userModel: TheUserModel, startPom: Callable[[float, float], None]
    ) -> PomStartResult:
        userModel.userInterface.intervalProgress(1.0)
        userModel.userInterface.intervalEnd()
        return handleIdleStartPom(userModel, startPom)


AnyInterval = Pomodoro | Break | GracePeriod | StartPrompt
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


@dataclass
class IntentionSet:
    """
    An intention was set: i.e. a pomodoro was started.

    @note: contrast with L{IntentionCreatedEvent}; an intention may be I{set}
        multiple times, but it is I{created} only once.
    """

    intention: Intention
    time: float
    duration: float
    streakLength: int
    """
    How long the intention was set for.
    """

    @property
    def points(self) -> int:
        """
        Setting an intention yields 1 point.
        """
        return int(2**self.streakLength)


_is_score_event = IntentionSet


@dataclass
class EvaluationScore:
    """
    Evaluating an intention gives a point.
    """

    time: float
    points: float = field(default=1)


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
    hypothetical = replace(
        model,
        _intentions=model._intentions[:],
        _interfaceFactory=lambda whatever: NoUserInterface(),
        _userInterface=NoUserInterface(),
        _upcomingDurations=split(),
        _sessions=[],
        _allStreaks=[each[:] for each in model._allStreaks],
    )
    # because it's init=False we have to copy it manually
    hypothetical._lastUpdateTime = model._lastUpdateTime

    debug("advancing to activity start", model._lastUpdateTime, activityStart)
    hypothetical.advanceToTime(activityStart)

    while hypothetical._lastUpdateTime <= workPeriodEnd:
        if hypothetical._activeInterval is not None:
            debug("advancing to interval end")
            hypothetical.advanceToTime(
                hypothetical._activeInterval.endTime + 1
            )
            if isinstance(hypothetical._activeInterval, Pomodoro):
                hypothetical.evaluatePomodoro(
                    hypothetical._activeInterval, EvaluationResult.achieved
                )
            # TODO: when estimation gets a score, make sure to put one that
            # is exactly correct here.
        if isinstance(hypothetical._activeInterval, (type(None), GracePeriod)):
            # We are either idle or in a grace period, so we should
            # immediately start a pomodoro.

            intention = hypothetical.addIntention("placeholder", None)
            startResult = hypothetical.startPomodoro(intention)
            assert startResult in {
                PomStartResult.Started,
                PomStartResult.Continued,
            }, "invariant failed: could not actually start pomodoro"
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
    currentIdeal = idealFuture(model, model._lastUpdateTime, workPeriodEnd)
    idealScoreNow = list(currentIdeal.scoreEvents(endTime=workPeriodEnd))
    if not idealScoreNow:
        return IdealScoreInfo(
            now=model._lastUpdateTime,
            idealScoreNow=idealScoreNow,
            workPeriodEnd=workPeriodEnd,
            nextPointLoss=None,
            idealScoreNext=idealScoreNow,
        )
    pointLossTime = idealScoreNow[-1].time
    return IdealScoreInfo(
        now=model._lastUpdateTime,
        idealScoreNow=idealScoreNow,
        workPeriodEnd=workPeriodEnd,
        nextPointLoss=pointLossTime,
        idealScoreNext=list(
            (
                idealFuture(model, pointLossTime, workPeriodEnd)
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
        for intention in self._intentions:
            for event in intention.scoreEvents():
                if event.time > endTime:
                    break
                yield event
        for streak in self._allStreaks:
            for interval in streak:
                if interval.startTime > startTime:
                    for event in interval.scoreEvents():
                        debug(
                            "score", event.time > endTime, event, event.points
                        )
                        if event.time > endTime:
                            break
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
        return [i for i in self._intentions if not i.completed and not i.abandoned]

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
        if (
            result == EvaluationResult.achieved
        ):
            assert pomodoro.intention.completed, "evaluation was set, should be complete"
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
