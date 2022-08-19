from dataclasses import dataclass, field
from typing import Type
from unittest import TestCase

from twisted.internet.interfaces import IReactorTime
from twisted.internet.task import Clock

from .model2 import AnUserInterface, Intention, IntervalType, TheUserModel


@dataclass
class TestInterval:
    """
    A record of methods being called on L{TestUserInterface}
    """
    intervalType: IntervalType
    startTime: float | None = None
    endTime: float | None = None
    currentProgress: float | None = None


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


intention: Type[AnUserInterface] = TestUserInterface


class ModelTests(TestCase):
    """
    Model tests.
    """

    def test_getStarted(self) -> None:
        """
        Get started.
        """
        c = Clock()
        tui = TestUserInterface(c)
        userModel = TheUserModel(c.seconds(), lambda it: tui)
        c.advance(1000)
        first = userModel.addIntention("first intention", 100.0)
        second = userModel.addIntention("second intention", None)
        third = userModel.addIntention("third intention", 50.0)
        c.advance(2000)
        self.assertEqual(userModel.intentions, [first, second, third])
        self.assertEqual(userModel.intentions, tui.sawIntentions)
        c.advance(3000)
        userModel.startPomodoro(first)
        print(tui.actions)
