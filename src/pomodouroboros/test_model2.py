from dataclasses import dataclass, field
from typing import Generic, Type, TypeVar, cast
from unittest import TestCase

from twisted.internet.interfaces import IReactorTime
from twisted.internet.task import Clock

from .model2 import AnUserInterface, Intention, IntervalType, TheUserModel
from pomodouroboros.model2 import AnyInterval, Break, GracePeriod, Pomodoro


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
        userModel.startPomodoro(first)
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
            tui.actions,
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
        )
        # time starts passing
        update((5 * 60) + 1)
        finalFirstInterval = TestInterval(
                    expectedFirstPom,
                    actualStartTime=4000.0,
                    actualEndTime=4304.0,
                    currentProgress=[
                        *[(each / expectedDuration) for each in [1, 2, 3]],
                        1.0,
                    ],
                )
        self.assertEqual(
            tui.actions,
            [
                finalFirstInterval
            ],
        )
        update(10)
        expectedBreak = Break(startTime=4300.0, endTime=4600.0)
        self.assertEqual(
            tui.actions,
            [
                finalFirstInterval,
                TestInterval(
                    expectedBreak,
                    actualStartTime=4303.0,
                    actualEndTime=None,
                    currentProgress=[],
                )
            ],
        )
