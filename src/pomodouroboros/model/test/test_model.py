from dataclasses import dataclass, field
from typing import Generic, Type, TypeVar, cast
from unittest import TestCase

from twisted.internet.interfaces import IReactorTime
from twisted.internet.task import Clock

from ..boundaries import UIEventListener, EvaluationResult, PomStartResult
from ..debugger import debug
from ..ideal import idealScore
from ..intention import Intention
from ..intervals import (
    AnyInterval,
    Break,
    Evaluation,
    GracePeriod,
    Pomodoro,
    StartPrompt,
)
from ..nexus import Nexus


@dataclass
class TestInterval:
    """
    A record of methods being called on L{TestUserInterface}
    """

    interval: AnyInterval
    actualStartTime: float | None = None
    actualEndTime: float | None = None
    currentProgress: list[float] = field(default_factory=list)


T = TypeVar("T")


@dataclass
class TestUserInterface:
    """
    Implementation of all UIEventListener protocols.
    """

    theNexus: Nexus = field(init=False)
    clock: IReactorTime
    actions: list[TestInterval] = field(default_factory=list)
    sawIntentions: list[Intention] = field(default_factory=list)
    abandonedIntentions: list[Intention] = field(default_factory=list)
    completedIntentions: list[Intention] = field(default_factory=list)

    def intervalProgress(self, percentComplete: float) -> None:
        """
        The active interval has progressed to C{percentComplete} percentage
        complete.
        """
        self.actions[-1].currentProgress.append(percentComplete)

    def intervalStart(self, interval: AnyInterval) -> None:
        """
        An interval has started, record it.
        """
        debug("interval: start!", interval)
        self.actions.append(TestInterval(interval, self.clock.seconds()))

    def intervalEnd(self) -> None:
        """
        The interval has ended. Hide the progress bar.
        """
        self.actions[-1].actualEndTime = self.clock.seconds()

    def intentionAdded(self, intention: Intention) -> None:
        """
        An intention was added to the set of intentions.
        """
        self.sawIntentions.append(intention)

    def intentionCompleted(self, intention: Intention) -> None:
        """
        The given intention was completed.
        """
        self.completedIntentions.append(intention)

    def intentionAbandoned(self, intention: Intention) -> None:
        """
        The given intention was abandoned.
        """
        self.abandonedIntentions.append(intention)

    def setIt(self, nexus: Nexus) -> UIEventListener:
        self.theNexus = nexus
        return self

    def clear(self) -> None:
        """
        Clear the actions log so we can assert about just the interesting
        parts.
        """
        filtered = [
            action for action in self.actions if action.actualEndTime is None
        ]
        self.actions[:] = filtered


intention: Type[UIEventListener] = TestUserInterface


class NexusTests(TestCase):
    """
    Nexus tests.
    """

    userMode: Nexus

    def setUp(self) -> None:
        """
        Set up this test case.
        """
        self.maxDiff = 9999
        self.clock = Clock()
        self.testUI = TestUserInterface(self.clock)
        self.nexus = Nexus(self.clock.seconds(), self.testUI.setIt)

    def advanceTime(self, n: float) -> None:
        """
        Advance the virtual timestamp of this test to the current time + C{n}
        where C{n} is a number of seconds.
        """
        debug("advancing", n)
        self.clock.advance(n)
        debug("to", self.clock.seconds())
        self.nexus.advanceToTime(self.clock.seconds())

    def test_idealScoreNotifications(self) -> None:
        """
        When the user has a session started, they will receive notifications
        telling them about decreases to their potential maximum score.
        """
        sessionStart = 1000
        realTimeStartDelay = 100.0
        self.nexus.addSession(sessionStart, 2000)
        self.advanceTime(sessionStart + realTimeStartDelay)
        self.advanceTime(1.0)
        self.advanceTime(1.0)
        self.advanceTime(1.0)
        self.advanceTime(1.0)
        self.advanceTime(1.0)
        self.advanceTime(197.0)
        self.advanceTime(100.0)
        self.advanceTime(103.0)

        self.assertEqual(
            [
                TestInterval(
                    interval=StartPrompt(
                        startTime=1100.0, endTime=1400.0, pointsLost=3.0
                    ),
                    actualStartTime=1100.0,
                    actualEndTime=1402.0,
                    currentProgress=[
                        0.0,
                        0.0033333333333333335,
                        0.006666666666666667,
                        0.01,
                        0.013333333333333334,
                        0.016666666666666666,
                        0.6733333333333333,
                        1.0,
                    ],
                ),
                TestInterval(
                    interval=StartPrompt(
                        startTime=1402.0, endTime=1700.0, pointsLost=11.25
                    ),
                    actualStartTime=1402.0,
                    actualEndTime=None,
                    currentProgress=[0.0, 0.34563758389261745],
                ),
            ],
            self.testUI.actions,
        )

    def test_startDuringSession(self) -> None:
        """
        When a session is running (and therefore, a 'start' prompt /
        score-decrease timer interrval is running) starting a pomodoro stops
        that timer and begins a pomodoro.
        """
        intention = self.nexus.addIntention("x", None)
        self.nexus.addSession(1000, 2000)
        self.advanceTime(100)  # no-op; time before session
        self.advanceTime(1000)  # enter session
        self.advanceTime(50)  # time in session before pomodoro
        self.nexus.startPomodoro(intention)
        self.advanceTime(120)  # enter pomodoro
        self.assertEqual(
            [
                TestInterval(
                    interval=StartPrompt(
                        startTime=1100.0, endTime=1400.0, pointsLost=3.0
                    ),
                    actualStartTime=1100.0,
                    actualEndTime=1150.0,
                    currentProgress=[
                        0.0,
                        50.0 / 300.0,
                        1.0,
                    ],
                ),
                TestInterval(
                    interval=Pomodoro(
                        intention=intention,
                        startTime=1150.0,
                        endTime=1150.0 + (5.0 * 60.0),
                        indexInStreak=0,
                    ),
                    actualStartTime=1150.0,
                    actualEndTime=None,
                    currentProgress=[
                        120 / (5 * 60.0),
                    ],
                ),
            ],
            self.testUI.actions,
        )

    def test_idealScore(self) -> None:
        """
        The ideal score should be the best sequence of events that the user
        could execute.
        """
        self.advanceTime(1000)
        ideal = idealScore(self.nexus, 2000.0)
        self.assertEqual(ideal.nextPointLoss, 1400.0)
        pointsForBreak = 1.0
        pointsForSecondIntentionSet = 2.0
        self.assertEqual(
            ideal.pointsLost(), pointsForBreak + pointsForSecondIntentionSet
        )
        self.advanceTime(1600)
        ideal = idealScore(self.nexus, 2000.0)
        self.assertEqual(ideal.nextPointLoss, None)
        self.assertEqual(ideal.pointsLost(), 0.0)

    def test_exactAdvance(self) -> None:
        """
        If you advance to exactly the boundary between pomodoro and break it
        should work ok.
        """

        self.advanceTime(5.0)
        i = self.nexus.addIntention("i", None)
        self.nexus.startPomodoro(i)
        self.advanceTime(5 * 60.0)
        self.assertEqual(
            [
                TestInterval(
                    Pomodoro(5.0, i, 5 + 5.0 * 60, indexInStreak=0),
                    actualStartTime=5.0,
                    actualEndTime=(5.0 + 5 * 60),
                    currentProgress=[1.0],
                ),
                TestInterval(
                    Break(5 + 5.0 * 60, 5 + (5 * 60.0 * 2)),
                    actualStartTime=5 + 5.0 * 60,
                    actualEndTime=None,
                    currentProgress=[
                        0.0,
                    ],
                ),
            ],
            self.testUI.actions,
        )

    def test_story(self) -> None:
        """
        Full story testing various features of a day of using Pomodouroboros.
        """
        # TODO: obviously a big omnibus thing like this is not good, but this
        # was a combination of bootstrapping the tests working through the
        # nexus's design.  Split it up later.

        # Some time passes before intentions are added.  Nothing should really
        # happen (but if we add a discrete timestamp for logging intention
        # creations, this will be when it is).
        self.advanceTime(1000)

        # User types in some intentions and sets estimates for some of them
        # TBD: should there be a prompt?
        first = self.nexus.addIntention("first intention", 100.0)
        second = self.nexus.addIntention("second intention", None)
        third = self.nexus.addIntention("third intention", 50.0)
        self.assertEqual(self.nexus.intentions, [first, second, third])
        self.assertEqual(self.nexus.intentions, self.testUI.sawIntentions)

        # Some time passes so we can set a baseline for pomodoro timing
        # (i.e. our story doesn't start at time 0).
        self.advanceTime(3000)

        # Start our first pomodoro with our first intention.
        self.assertEqual(
            self.nexus.startPomodoro(first), PomStartResult.Started
        )
        self.assertEqual(first.pomodoros, [self.testUI.actions[0].interval])

        # No time has passed. We can't start another pomodoro; the first one is
        # already running.
        self.assertEqual(
            self.nexus.startPomodoro(second), PomStartResult.AlreadyStarted
        )
        self.assertEqual(second.pomodoros, [])

        # Advance time 3 times, creating 3 records of progress.
        self.advanceTime(1)
        self.advanceTime(1)
        self.advanceTime(1)

        # We expect our first pomodoro to be 5 minutes long.
        expectedDuration = 5 * 60
        expectedFirstPom = Pomodoro(
            startTime=4000.0,
            endTime=4000.0 + expectedDuration,
            intention=first,
            indexInStreak=0,
        )
        self.assertEqual(
            [
                TestInterval(
                    expectedFirstPom,
                    actualStartTime=4000.0,
                    actualEndTime=None,
                    currentProgress=[
                        (each / expectedDuration) for each in [1, 2, 3]
                    ],
                )
            ],
            self.testUI.actions,
        )

        # Advance past the end of the pomodoro, into a break.
        self.advanceTime((5 * 60) + 1)

        # This is the break we expect to see; also 5 minutes.
        expectedBreak = Break(startTime=4300.0, endTime=4600.0)
        self.assertEqual(
            [
                TestInterval(
                    expectedFirstPom,
                    actualStartTime=4000.0,
                    actualEndTime=4304.0,
                    currentProgress=[
                        *[(each / expectedDuration) for each in [1, 2, 3]],
                        1.0,
                    ],
                ),
                TestInterval(
                    expectedBreak,
                    actualStartTime=4304.0,
                    actualEndTime=None,
                    currentProgress=[4 / expectedDuration],
                ),
            ],
            self.testUI.actions,
        )
        self.testUI.clear()

        # Move past the end of the break, into a grace period at the beginning
        # of the next pomodoro.
        self.advanceTime(10)
        self.assertEqual(
            [
                TestInterval(
                    expectedBreak,
                    actualStartTime=4304.0,
                    actualEndTime=None,
                    currentProgress=[
                        (each / expectedDuration) for each in [4, 14]
                    ],
                ),
            ],
            self.testUI.actions,
        )

        # Advance into the grace period, but not past the end of the grace
        # period
        self.advanceTime((5 * 60) - 13)
        expectedGracePeriod = GracePeriod(4600.0, 5200.0)
        self.assertEqual(
            [
                TestInterval(
                    expectedBreak,
                    actualStartTime=4304.0,
                    actualEndTime=4300.0 + (5.0 * 60.0) + 1,  # break is over
                    currentProgress=[
                        *[(each / expectedDuration) for each in [4, 14]],
                        1.0,
                    ],
                ),
                TestInterval(
                    expectedGracePeriod,
                    actualStartTime=4601.0,
                    currentProgress=[
                        each
                        / (
                            expectedGracePeriod.endTime
                            - expectedGracePeriod.startTime
                        )
                        for each in [1]
                    ],
                ),
            ],
            self.testUI.actions,
        )
        self.testUI.clear()

        # Advance past the end of the grace period.
        self.advanceTime(10 * 60)
        self.assertEqual(
            [
                TestInterval(
                    expectedGracePeriod,
                    actualStartTime=4601.0,
                    currentProgress=[
                        *(
                            each
                            / (
                                expectedGracePeriod.endTime
                                - expectedGracePeriod.startTime
                            )
                            for each in [1]
                        ),
                        1.0,
                    ],
                    actualEndTime=5201.0,  # Grace period is over.
                ),
            ],
            self.testUI.actions,
        )
        self.testUI.clear()

        # Advance really far to offset our second streak.
        self.advanceTime(5000)
        # Nothing happens despite the >80 minutes passing, as time is advancing
        # outside of a streak or session.
        self.assertEqual([], self.testUI.actions)

        # OK, start a second streak.
        self.assertEqual(
            self.nexus.startPomodoro(second), PomStartResult.Started
        )

        # Advance past the end of the pomodoro, into the break.
        self.advanceTime((5 * 60) + 1.0)
        # Try to start a second pomodoro during the break; you can't. You're on
        # a break.
        self.assertEqual(
            self.nexus.startPomodoro(second), PomStartResult.OnBreak
        )
        # Advance out of the end of the break, into the next pomodoro
        self.advanceTime((5 * 60) + 1.0)
        self.assertEqual(
            [
                TestInterval(
                    interval=Pomodoro(
                        startTime=10201.0,
                        intention=second,
                        endTime=10501.0,
                        indexInStreak=0,
                    ),
                    actualStartTime=10201.0,
                    actualEndTime=10502.0,
                    # No progress, since we skipped the whole thing.
                    currentProgress=[1.0],
                ),
                TestInterval(
                    interval=Break(startTime=10501.0, endTime=10801.0),
                    actualStartTime=10502.0,
                    actualEndTime=10803.0,
                    # Jumped in right at the beginning, went way out past the
                    # end
                    currentProgress=[0.0033333333333333335, 1.0],
                ),
                TestInterval(
                    interval=GracePeriod(
                        startTime=10801.0, originalPomEnd=11401.0
                    ),
                    actualStartTime=10803.0,
                    actualEndTime=None,
                    # Grace period has just started, it has not ended yet
                    currentProgress=[0.01],
                ),
            ],
            self.testUI.actions,
        )
        self.testUI.clear()

        # For the first time we're starting a pomdoro from *within* a grace
        # period, so we are continuing a streak.
        self.assertEqual(
            self.nexus.startPomodoro(third), PomStartResult.Continued
        )
        self.assertEqual(
            [
                TestInterval(
                    interval=GracePeriod(
                        startTime=10801.0, originalPomEnd=11401.0
                    ),
                    actualStartTime=10803.0,
                    actualEndTime=None,  # period should probably end before pom starts
                    currentProgress=[0.01],
                ),
                TestInterval(
                    interval=Pomodoro(
                        startTime=10801.0,  # the "start time" of the pomodoro
                        # actually *matches* that of the
                        # grace period.
                        intention=third,
                        endTime=11401.0,
                        indexInStreak=1,
                    ),
                    actualStartTime=10803.0,
                    actualEndTime=None,
                    currentProgress=[],
                ),
            ],
            self.testUI.actions,
        )

        # test for scoring
        events = list(self.nexus.scoreEvents())

        # currently the score is 1 point for the first pomdoro in a streak and
        # 4 points for the second
        points_for_first_interval = 1
        points_for_second_interval = 2
        points_for_intention = 3
        points_for_estimation = 1
        points_for_break = 1.0

        self.assertEqual(
            sum(each.points for each in events),
            # 2 first-in-streak pomodoros, 1 second-in-streak
            (points_for_first_interval * 2)
            + (points_for_second_interval)
            + (3 * points_for_intention)
            + (2 * points_for_estimation)
            + (2 * points_for_break),
        )

        from json import dumps, loads
        from ..storage import nexusToJSON, nexusFromJSON

        roundTrip = nexusFromJSON(
            loads(dumps(nexusToJSON(self.nexus))),
            lambda nexus: self.nexus.userInterface,
        )
        self.maxDiff = 99999
        self.assertEqual(self.nexus._initialTime, roundTrip._initialTime)
        self.assertEqual(self.nexus._intentions, roundTrip._intentions)
        self.assertEqual(self.nexus._activeInterval, roundTrip._activeInterval)
        self.assertEqual(self.nexus._lastUpdateTime, roundTrip._lastUpdateTime)
        self.assertEqual(
            list(self.nexus.cloneWithoutUI()._upcomingDurations),
            list(roundTrip.cloneWithoutUI()._upcomingDurations),
        )
        self.assertEqual(self.nexus._rules, roundTrip._rules)
        self.assertEqual(self.nexus._streaks, roundTrip._streaks)
        self.assertEqual(self.nexus._sessions, roundTrip._sessions)

    def test_achievedEarly(self) -> None:
        """
        If I achieve the desired intent of a pomodoro while it is still
        running, that pomodoro should really be marked as done, and the next
        break should start immediately.
        """
        START_TIME = 1234.0
        self.advanceTime(START_TIME)

        intent = self.nexus.addIntention("early completion intention", None)

        self.assertEqual(
            self.nexus.startPomodoro(intent), PomStartResult.Started
        )

        DEFAULT_DURATION = 5.0 * 60.0
        EARLY_COMPLETION = DEFAULT_DURATION / 3

        self.advanceTime(EARLY_COMPLETION)
        action = self.testUI.actions[0].interval
        assert isinstance(action, Pomodoro)
        self.assertEqual(self.nexus.availableIntentions, [intent])
        self.assertEqual(self.testUI.completedIntentions, [])
        self.nexus.evaluatePomodoro(action, EvaluationResult.achieved)
        self.assertEqual(self.nexus.availableIntentions, [])
        self.assertEqual(self.testUI.completedIntentions, [intent])
        self.advanceTime(1)
        self.assertEqual(
            [
                TestInterval(
                    interval=Pomodoro(
                        startTime=START_TIME,  # the "start time" of the pomodoro
                        # actually *matches* that of the
                        # grace period.
                        intention=intent,
                        endTime=START_TIME + EARLY_COMPLETION,
                        evaluation=Evaluation(
                            EvaluationResult.achieved,
                            START_TIME + EARLY_COMPLETION,
                        ),
                        indexInStreak=0,
                    ),
                    actualStartTime=START_TIME,
                    actualEndTime=START_TIME + EARLY_COMPLETION,
                    currentProgress=[1 / 3, 1.0],
                ),
                TestInterval(
                    interval=Break(
                        startTime=START_TIME + EARLY_COMPLETION,
                        endTime=START_TIME
                        + EARLY_COMPLETION
                        + DEFAULT_DURATION,
                    ),
                    actualStartTime=START_TIME + EARLY_COMPLETION,
                    actualEndTime=None,
                    # Jumped in right at the beginning, went way out past the
                    # end
                    currentProgress=[
                        0.0,  # is this desirable?
                        0.0033333333333333335,
                    ],
                ),
            ],
            self.testUI.actions,
        )

    def test_evaluatedNotAchievedEarly(self) -> None:
        """
        Evaluating an ongoing pomodoro as some other status besides 'achieved'
        will not stop it early.
        """
        START_TIME = 1234.0
        self.advanceTime(START_TIME)

        intent = self.nexus.addIntention("early completion intention", None)

        self.assertEqual(
            self.nexus.startPomodoro(intent), PomStartResult.Started
        )

        DEFAULT_DURATION = 5.0 * 60.0
        EARLY_COMPLETION = DEFAULT_DURATION / 3

        self.advanceTime(EARLY_COMPLETION)
        action = self.testUI.actions[0].interval
        assert isinstance(action, Pomodoro)
        self.nexus.evaluatePomodoro(action, EvaluationResult.distracted)
        self.advanceTime(1)
        self.assertEqual(
            [
                TestInterval(
                    interval=Pomodoro(
                        startTime=START_TIME,
                        intention=intent,
                        endTime=START_TIME + DEFAULT_DURATION,
                        evaluation=Evaluation(
                            EvaluationResult.distracted,
                            START_TIME + EARLY_COMPLETION,
                        ),
                        indexInStreak=0,
                    ),
                    actualStartTime=START_TIME,
                    actualEndTime=None,
                    currentProgress=[1 / 3, (1.0 / 3) + (1 / (5.0 * 60))],
                ),
            ],
            self.testUI.actions,
        )

    def test_evaluationScore(self) -> None:
        """
        Evaluating a pomdooro as focused on an intention should give us 1 point.
        """
        self.advanceTime(1)
        intent = self.nexus.addIntention("intent", None)
        self.nexus.startPomodoro(intent)
        self.advanceTime((5 * 60.0) + 1)
        pom = self.testUI.actions[0].interval
        assert isinstance(pom, Pomodoro)

        def currentPoints() -> float:
            events = list(self.nexus.scoreEvents())
            debug([(each, each.points) for each in events])
            return sum(each.points for each in events)

        before = currentPoints()
        self.nexus.evaluatePomodoro(pom, EvaluationResult.focused)
        after = currentPoints()
        self.assertEqual(after - before, 1.0)
