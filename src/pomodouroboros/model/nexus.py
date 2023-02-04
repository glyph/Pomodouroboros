from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field, replace
from typing import Callable, Iterable, Iterator, Sequence

from .boundaries import EvaluationResult, IntervalType, NoUserInterface, PomStartResult, ScoreEvent, UIEventListener, UserInterfaceFactory
from .debugger import debug
from .ideal import idealScore
from .intention import Estimate, Intention
from .intervals import AnyInterval, Break, Duration, Evaluation, GracePeriod, Pomodoro, Session, StartPrompt, handleIdleStartPom


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

_theNoUserInterface = NoUserInterface()
def _noUIFactory() -> NoUserInterface:
    return _theNoUserInterface

@dataclass
class Nexus:
    """
    Nexus where all the models of the user's ongoing pomodoro experience are
    coordinated, dispatched, and collected for things like serialization.
    """

    _initialTime: float
    _interfaceFactory: UserInterfaceFactory
    _intentions: list[Intention] = field(default_factory=list)
    _activeInterval: AnyInterval | None = None
    """
    The list of active streak intervals currently being worked on.
    """

    _lastUpdateTime: float = field(init=False, default=0.0)
    _userInterface: UIEventListener | None = None
    _upcomingDurations: Iterator[Duration] = iter(())
    _rules: GameRules = field(default_factory=GameRules)

    _streaks: list[list[AnyInterval]] = field(default_factory=lambda: [[]])
    """
    The list of previous streaks, each one being a list of its intervals, that
    are now completed.
    """
    _sessions: list[Session] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self._initialTime > self._lastUpdateTime:
            self.advanceToTime(self._initialTime)

    def cloneWithoutUI(self) -> Nexus:
        """
        Create a deep copy of this L{Nexus}, detached from any user interface,
        to perform hypothetical model interactions.
        """
        previouslyUpcoming = list(self._upcomingDurations)

        def split() -> Iterator[Duration]:
            return iter(previouslyUpcoming)

        self._upcomingDurations = split()
        hypothetical = deepcopy(
            replace(
                self,
                _intentions=self._intentions[:],
                _interfaceFactory=_noUIFactory,
                _userInterface=_theNoUserInterface,
                _upcomingDurations=split(),
                _sessions=[],
                _streaks=[each[:] for each in self._streaks],
            )
        )
        # because it's init=False we have to copy it manually
        hypothetical._lastUpdateTime = self._lastUpdateTime
        return hypothetical

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
        for streak in self._streaks:
            for interval in streak:
                if interval.startTime > startTime:
                    for event in interval.scoreEvents():
                        debug(
                            "score", event.time > endTime, event, event.points
                        )
                        if event.time <= endTime:
                            yield event

    @property
    def userInterface(self) -> UIEventListener:
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
            self._streaks[-1].append(new)
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
                    self._streaks.append([])
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
        self, title: str="", description: str="", estimate: float | None=None
    ) -> Intention:
        """
        Add an intention with the given description and time estimate.
        """
        self._intentions.append(
            newIntention := Intention(self._lastUpdateTime, title, description)
        )
        if estimate is not None:
            newIntention.estimates.append(
                Estimate(
                    duration=estimate, madeAt=self._lastUpdateTime
                )
            )
        self.userInterface.intentionAdded(newIntention)
        return newIntention

    def addSession(self, startTime: float, endTime: float) -> None:
        """
        Add a 'work session'; a discrete interval where we will be scored, and
        notified of potential drops to our score if we don't set intentions.
        """
        self._sessions.append(Session(startTime, endTime))
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
                    isinstance(each, Pomodoro) for each in self._streaks[-1]
                ),
                startTime=startTime,
                endTime=endTime,
            )
            intention.pomodoros.append(newPomodoro)
            self._activeInterval = newPomodoro
            self._streaks[-1].append(newPomodoro)
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


preludeIntervalMap: dict[IntervalType, type[GracePeriod | Break]] = {
    Pomodoro.intervalType: GracePeriod,
    Break.intervalType: Break,
}


def nextInterval(
    nexus: Nexus,
    timestamp: float,
    previousInterval: AnyInterval | None,
) -> AnyInterval | None:
    """
    Determine what the next interval should be.
    """
    duration = next(nexus._upcomingDurations, None)
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
    for session in nexus._sessions:
        if session.start <= timestamp < session.end:
            debug("session active", session.start, session.end)
            break
    else:
        debug("no session")
        return None

    scoreInfo = idealScore(nexus, session.end)
    nextDrop = scoreInfo.nextPointLoss
    debug(nextDrop)
    if nextDrop is None:
        return None
    if nextDrop <= timestamp:
        return None
    debug(f"{timestamp=} {nextDrop=}")
    return StartPrompt(timestamp, nextDrop, scoreInfo.pointsLost())
