from dataclasses import dataclass, field
from typing import Generic, Type, TypeVar, cast
from unittest import TestCase

from twisted.internet.interfaces import IReactorTime
from twisted.internet.task import Clock

from .model2 import AnUserInterface, Intention, IntervalType, TheUserModel
from pomodouroboros.model2 import Pomodoro


@dataclass
class TestInterval:
    """
    A record of methods being called on L{TestUserInterface}
    """

    intervalType: IntervalType
    startTime: float | None = None
    endTime: float | None = None
    currentProgress: float | None = None


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
        self.actions[-1].currentProgress = percentComplete

    def intervalStart(self, intervalType: IntervalType) -> None:
        """
        Set the interval type to "pomodoro".
        """
        self.actions.append(TestInterval(intervalType, self.clock.seconds()))

    def intervalEnd(self) -> None:
        """
        The interval has ended. Hide the progress bar.
        """

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
        update(3000)
        newPomodoro = userModel.startPomodoro(first)
        self.assertEqual(
            newPomodoro,
            Pomodoro(
                startTime=4000.0, endTime=4000.0 + (5 * 60), intention=first
            ),
        )
        self.assertEqual(
            tui.actions,
            [
                TestInterval(
                    Pomodoro.intervalType,
                    startTime=4000.0,
                    endTime=None,
                    currentProgress=None,
                )
            ],
        )
        # time starts passing
        update(4000.0 + (6 * 60))
        self.assertEqual(
            tui.actions,
            [
                TestInterval(
                    Pomodoro.intervalType,
                    startTime=4000.0,
                    endTime=None,
                    currentProgress=None,
                )
            ],
        )
