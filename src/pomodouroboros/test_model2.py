from dataclasses import dataclass, field
from typing import Generic, Type, TypeVar, cast
from unittest import TestCase

from .model2 import AnUserInterface, Intention, IntervalType, TheUserModel
from pomodouroboros.model2 import (
    AnyInterval,
    Break,
    GracePeriod,
    PomStartResult,
    Pomodoro,
)
from twisted.internet.interfaces import IReactorTime
from twisted.internet.task import Clock


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

DEBUG = False


@dataclass
class TestUserInterface:
    """
    Implementation of AnUserInterface protocol.
    """

    theModel: TheUserModel = field(init=False)
    clock: IReactorTime
    actions: list[TestInterval] = field(default_factory=list)
    sawIntentions: list[Intention] = field(default_factory=list)

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
        if DEBUG:
            print("interval: start!", interval)
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

    def setIt(self, model: TheUserModel) -> AnUserInterface:
        self.theModel = model
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


intention: Type[AnUserInterface] = TestUserInterface


class ModelTests(TestCase):
    """
    Model tests.
    """

    def test_story(self) -> None:
        """
        Full story testing all the features of a day of using Pomodouroboros.
        """
        self.maxDiff = 99999
        c = Clock()

        tui = TestUserInterface(c)
        userModel = TheUserModel(c.seconds(), tui.setIt)

        def update(n: float) -> None:
            c.advance(n)
            userModel.advanceToTime(c.seconds())

        update(1000)
        # User types in some intentions and sets estimates for some of them
        # TBD: should there be a prompt?
        first = userModel.addIntention("first intention", 100.0)
        second = userModel.addIntention("second intention", None)
        third = userModel.addIntention("third intention", 50.0)
        self.assertEqual(userModel.intentions, [first, second, third])
        self.assertEqual(userModel.intentions, tui.sawIntentions)
        # Some time passes so we can set a baseline for pomodoro timing.
        def progresses() -> list[float]:
            return []

        update(3000)
        self.assertEqual(
            userModel.startPomodoro(first), PomStartResult.Started
        )
        self.assertEqual(
            userModel.startPomodoro(second), PomStartResult.AlreadyStarted
        )
        update(1)
        update(1)
        update(1)
        expectedDuration = 5 * 60
        expectedFirstPom = Pomodoro(
            startTime=4000.0,
            endTime=4000.0 + expectedDuration,
            intention=first,
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
            tui.actions,
        )
        # time starts passing
        update((5 * 60) + 1)
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
            tui.actions,
        )
        tui.clear()
        update(10)
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
            tui.actions,
        )
        update((5 * 60) - 13)
        expectedGracePeriod = GracePeriod(4600.0, 5200.0)
        self.assertEqual(
            [
                TestInterval(
                    expectedBreak,
                    actualStartTime=4304.0,
                    actualEndTime=4300.0 + (5.0 * 60.0) + 1,
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
            tui.actions,
        )
        tui.clear()
        update(10 * 60)
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
                    actualEndTime=5201.0,
                ),
            ],
            tui.actions,
        )
        tui.clear()
        update(5000)
        self.assertEqual([], tui.actions)
        self.assertEqual(
            userModel.startPomodoro(second), PomStartResult.Started
        )
        update((5 * 60) + 1.0)
        self.assertEqual(
            userModel.startPomodoro(second), PomStartResult.OnBreak
        )
        update((5 * 60) + 1.0)
        self.assertEqual(
            [
                TestInterval(
                    interval=Pomodoro(
                        startTime=10201.0,
                        intention=Intention(
                            description="second intention", estimate=None
                        ),
                        endTime=10501.0,
                    ),
                    actualStartTime=10201.0,
                    actualEndTime=10502.0,
                    currentProgress=[1.0],
                ),
                TestInterval(
                    interval=Break(startTime=10501.0, endTime=10801.0),
                    actualStartTime=10502.0,
                    actualEndTime=10803.0,
                    currentProgress=[0.0033333333333333335, 1.0],
                ),
                TestInterval(
                    interval=GracePeriod(startTime=10801.0, endTime=11401.0),
                    actualStartTime=10803.0,
                    actualEndTime=None,
                    currentProgress=[0.0033333333333333335],
                ),
            ],
            tui.actions,
        )
        tui.clear()
        self.assertEqual(
            userModel.startPomodoro(third), PomStartResult.Continued
        )
        self.assertEqual(
            [
                TestInterval(
                    interval=GracePeriod(startTime=10801.0, endTime=11401.0),
                    actualStartTime=10803.0,
                    actualEndTime=None,  # period should probably end before pom starts
                    currentProgress=[0.0033333333333333335],
                ),
                TestInterval(
                    interval=Pomodoro(
                        startTime=10801.0,
                        intention=third,
                        endTime=11401.0,
                    ),
                    actualStartTime=10803.0,
                    actualEndTime=None,
                    currentProgress=[],
                ),
            ],
            tui.actions,
        )
        events = list(userModel.scoreEventsSince(0))
        points_for_first_interval = 1
        points_for_second_interval = 4
        self.assertEqual(
            sum(each.points for each in events),
            (points_for_first_interval * 2) + (points_for_second_interval),
        )
