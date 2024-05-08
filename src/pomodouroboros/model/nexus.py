# -*- test-case-name: pomodouroboros.model.test -*-
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field, replace
from typing import Iterable, Iterator, MutableSequence, Sequence

from .boundaries import (
    EvaluationResult,
    IntervalType,
    NoUserInterface,
    PomStartResult,
    ScoreEvent,
    UIEventListener,
    UserInterfaceFactory,
)
from .debugger import debug
from .ideal import idealScore
from .intention import Estimate, Intention
from .intervals import (
    AnyStreakInterval,
    AnyIntervalOrIdle,
    Break,
    Duration,
    Evaluation,
    GracePeriod,
    Idle,
    Pomodoro,
    StartPrompt,
)
from .observables import IgnoreChanges, ObservableList
from .sessions import Session


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


_theNoUserInterface: UIEventListener = NoUserInterface()


def _noUIFactory(nexus: Nexus) -> UIEventListener:
    return _theNoUserInterface


@dataclass
class Nexus:
    """
    Nexus where all the models of the user's ongoing pomodoro experience are
    coordinated, dispatched, and collected for things like serialization.
    """

    _initialTime: float
    """
    An initial time specified during construction.  The nexus will advance to
    this time upon first construction.
    """
    # TODO: we could probably simplify and get rid of this; it ought to be
    # redundant with lastUpdateTime?

    _interfaceFactory: UserInterfaceFactory
    "A factory to create a user interface as the Nexus is being instantiated."

    _lastIntentionID: int
    """
    The last ID used for an intention, incremented by 1 each time a new one is
    created.
    """

    _intentions: MutableSequence[Intention] = field(
        default_factory=lambda: ObservableList(IgnoreChanges)
    )
    "A list of all the intentions that the user has specified."
    # TODO: intentions should be archived like streaks.

    _userInterface: UIEventListener | None = None
    "The user interface to deliver information to."

    _upcomingDurations: Iterator[Duration] = iter(())
    "The durations that are upcoming in the current streak."

    _rules: GameRules = field(default_factory=GameRules)
    "The rules of what constitutes a streak."

    _previousStreaks: list[list[AnyStreakInterval]] = field(default_factory=list)
    "An archive of the previous streaks that the user has completed."

    _currentStreak: list[AnyStreakInterval] = field(default_factory=list)
    "The user's current streak."

    _sessions: ObservableList[Session] = field(
        default_factory=lambda: ObservableList(IgnoreChanges)
    )

    _lastUpdateTime: float = field(default=0.0)

    def __post_init__(self) -> None:
        debug(f"post-init, IT={self._initialTime} LUT={self._lastUpdateTime}")
        if self._initialTime > self._lastUpdateTime:
            debug("post-init advance")
            self.advanceToTime(self._initialTime)
        else:
            debug("post-init, no advance")

    def _newIdleInterval(self) -> Idle:
        from math import inf

        nextSessionTime = next(
            (
                session.start
                for session in self._sessions
                if session.end > self._lastUpdateTime
                and session.start > self._lastUpdateTime
            ),
            inf,
        )
        return Idle(startTime=self._lastUpdateTime, endTime=nextSessionTime)

    @property
    def _activeInterval(self) -> AnyIntervalOrIdle:
        if not self._currentStreak:
            return self._newIdleInterval()

        candidateInterval = self._currentStreak[-1]
        now = self._lastUpdateTime

        if now < candidateInterval.startTime:
            # when would this happen? interval at the end of the current streak
            # somehow has not started?
            return self._newIdleInterval()

        if now > candidateInterval.endTime:
            # We've moved on past the end of the interval, so it is no longer
            # active.  Note: this corner of the logic is extremely finicky,
            # because evaluating the currently-executing pomodoro depends on it
            # *remaining* the _activeInterval while doing advanceToTime at the
            # current timestamp.  therefore '>=' would be incorrect here in an
            # important way, even though these values are normally real time
            # and therefore not meaningfully comparable on exact equality.
            debug("active interval: now after end")
            return self._newIdleInterval()
        debug("active interval: yay:", candidateInterval)
        return candidateInterval

    def cloneWithoutUI(self) -> Nexus:
        """
        Create a deep copy of this L{Nexus}, detached from any user interface,
        to perform hypothetical model interactions.
        """
        previouslyUpcoming = list(self._upcomingDurations)

        def split() -> Iterator[Duration]:
            return iter(previouslyUpcoming)

        self._upcomingDurations = split()
        debug("constructing hypothetical")
        hypothetical = deepcopy(
            replace(
                self,
                _intentions=self._intentions[:],
                _interfaceFactory=_noUIFactory,
                _userInterface=_theNoUserInterface,
                _upcomingDurations=split(),
                _sessions=ObservableList(IgnoreChanges),
                _previousStreaks=[
                    each[:] for each in self._previousStreaks
                ],
                # TODO: the intervals in the current streak are mutable (if we
                # evaluate the last one early, its end time changes) and thus
                # potentially need to be cloned here; however, the
                # idealized-evaluation logic should never do that, so this is
                # more of an academic point
                _currentStreak=self._currentStreak[:],
            )
        )
        debug("constructed")
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
                if startTime <= event.time and event.time <= endTime:
                    yield event
        for streak in self._previousStreaks + [self._currentStreak]:
            for interval in streak:
                if interval.startTime > startTime:
                    for event in interval.scoreEvents():
                        debug(
                            "score", event.time > endTime, event, event.points
                        )
                        if startTime <= event.time and event.time <= endTime:
                            yield event

    @property
    def userInterface(self) -> UIEventListener:
        """
        build the user interface on demand
        """
        if self._userInterface is None:
            debug("creating user interface for the first time")
            ui: UIEventListener = self._interfaceFactory(self)
            debug("creating user interface for the first time", ui)
            self._userInterface = ui
            active = self._activeInterval
            if active is not None:
                debug("UI reification interval start", active)
                ui.intervalStart(active)
            else:
                debug("UI reification but no interval running", self._streaks)
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

    def _activeSession(self) -> Session | None:
        for session in self._sessions:
            if session.start <= self._lastUpdateTime < session.end:
                debug("session active", session.start, session.end)
                return session
        debug("no session")
        return None

    def advanceToTime(self, newTime: float) -> None:
        """
        Advance to the epoch time given.
        """

        # ensure lazy user-interface is reified before we start updating so
        # that notifications of interval starts happen in the correct order
        # (particularly important so tests can be exact).
        self.userInterface

        debug("begin advance from", self._lastUpdateTime, "to", newTime)
        earlyEvaluationSpecialCase = (
            # if our current streak is not empty (i.e. we are continuing it)
            self._currentStreak
            # and the end time of the current interval in the current streak is
            # not set
            and (currentEndTime := self._currentStreak[-1].endTime) is not None
            # and the current end time happens to correspond *exactly* to the last update time
            and currentEndTime == self._lastUpdateTime
            # then even if the new time has not moved and we are still on the
            # last update time exactly, we need to process a loop update
            # because the timer at the end of the interval has moved.
        )
        while self._lastUpdateTime < newTime or earlyEvaluationSpecialCase:
            earlyEvaluationSpecialCase = False
            newInterval: AnyStreakInterval | None = None
            currentInterval = self._activeInterval
            if isinstance(currentInterval, Idle):
                # If there's no current interval then there's nothing to end
                # and we can skip forward to current time, and let the start
                # prompt just begin at the current time, not some point in the
                # past where some reminder *might* have been appropriate.
                self._lastUpdateTime = newTime
                debug("interval None, update to real time", newTime)
                activeSession = self._activeSession()
                if activeSession is not None:
                    scoreInfo = idealScore(
                        self, activeSession.start, activeSession.end
                    )
                    nextDrop = scoreInfo.nextPointLoss
                    if nextDrop is not None and nextDrop > newTime:
                        newInterval = StartPrompt(
                            self._lastUpdateTime,
                            nextDrop,
                            scoreInfo.scoreBeforeLoss(),
                            scoreInfo.scoreAfterLoss(),
                        )
            else:
                debug("interval active", newTime)
                if newTime >= currentInterval.endTime:
                    debug(
                        "newTime >= endTime", newTime, currentInterval.endTime
                    )
                    self._lastUpdateTime = currentInterval.endTime

                    if currentInterval.intervalType in {
                        GracePeriod.intervalType,
                        StartPrompt.intervalType,
                    }:
                        # New streaks begin when grace periods expire.
                        debug(
                            currentInterval.intervalType, "grace/prompt expiry"
                        )
                        self._upcomingDurations = iter(())

                    debug("getting duration", currentInterval.intervalType)
                    newDuration = next(self._upcomingDurations, None)
                    debug("first interface lookup")
                    self.userInterface.intervalProgress(1.0)
                    debug("second interface lookup")
                    self.userInterface.intervalEnd()
                    debug("testing newDuration")
                    if newDuration is None:
                        debug("no new duration, so catching up to real time")
                        # XXX needs test coverage
                        previous, self._currentStreak = self._currentStreak, []
                        assert previous, "rolling off the end of a streak but the streak is empty somehow"
                        self._previousStreaks.append(previous)
                    else:
                        debug("new duration", newDuration)
                        newInterval = preludeIntervalMap[
                            newDuration.intervalType
                        ](
                            currentInterval.endTime,
                            currentInterval.endTime + newDuration.seconds,
                        )
                else:
                    debug("newTime < endTime")
                    # We're landing in the middle of an interval, so we need to
                    # update its progress.  If it's in the middle then we can
                    # move time all the way forward.
                    self._lastUpdateTime = newTime
                    elapsedWithinInterval = newTime - currentInterval.startTime
                    intervalDuration = (
                        currentInterval.endTime - currentInterval.startTime
                    )
                    self.userInterface.intervalProgress(
                        elapsedWithinInterval / intervalDuration
                    )

            # if we created a new interval for any reason on this iteration
            # through the loop, then we need to mention that fact to the UI.
            if newInterval is not None:
                debug("newInterval created", newInterval)
                self._createdInterval(newInterval)
                # should really be active now
                assert self._activeInterval is newInterval

    def _createdInterval(self, newInterval: AnyStreakInterval) -> None:
        self._currentStreak.append(newInterval)
        self.userInterface.intervalStart(newInterval)
        self.userInterface.intervalProgress(0.0)

    def addIntention(
        self,
        title: str = "",
        description: str = "",
        estimate: float | None = None,
    ) -> Intention:
        """
        Add an intention with the given description and time estimate.
        """
        self._lastIntentionID += 1
        newID = self._lastIntentionID
        self._intentions.append(
            newIntention := Intention(
                newID,
                self._lastUpdateTime,
                self._lastUpdateTime,
                title,
                description,
            )
        )
        if estimate is not None:
            newIntention.estimates.append(
                Estimate(duration=estimate, madeAt=self._lastUpdateTime)
            )
        return newIntention

    def addManualSession(self, startTime: float, endTime: float) -> None:
        """
        Add a 'work session'; a discrete interval where we will be scored, and
        notified of potential drops to our score if we don't set intentions.
        """
        self._sessions.append(Session(startTime, endTime, False))
        # MutableSequence doesn't have a .sort() method
        self._sessions[:] = sorted(self._sessions)

    def startPomodoro(self, intention: Intention) -> PomStartResult:
        """
        When you start a pomodoro, the length of time set by the pomodoro is
        determined by your current streak so it's not a parameter.
        """

        def startPom(startTime: float, endTime: float) -> None:
            newPomodoro = Pomodoro(
                intention=intention,
                indexInStreak=sum(
                    isinstance(each, Pomodoro) for each in self._currentStreak
                ),
                startTime=startTime,
                endTime=endTime,
            )
            intention.pomodoros.append(newPomodoro)
            self._createdInterval(newPomodoro)

        return self._activeInterval.handleStartPom(self, startPom)

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

                # XXX this doesn't work any more, since we drive the loop based
                # on being out of date on the actual time.
                self.advanceToTime(self._lastUpdateTime)


preludeIntervalMap: dict[IntervalType, type[GracePeriod | Break]] = {
    Pomodoro.intervalType: GracePeriod,
    Break.intervalType: Break,
}
