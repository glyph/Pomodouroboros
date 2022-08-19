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
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import ClassVar, Generic, Protocol, Sequence, TypeVar

class IntervalType(Enum):
    """
    The type of a given interval.
    """

    Pomodoro = "Pomodoro"
    GracePeriod = "GracePeriod"
    Break = "Break"


class AnUserInterface(Protocol):
    """
    Protocol that user interfaces must adhere to.
    """

    def intervalProgress(self, percentComplete: float) -> None:
        """
        The active interval has progressed to C{percentComplete} percentage
        complete.
        """

    def intervalStart(self, intervalType: IntervalType) -> None:
        """
        Set the interval type to "pomodoro".
        """

    def intervalEnd(self) -> None:
        """
        The interval has ended. Hide the progress bar.
        """

    def intentionAdded(self, intention: Intention) -> None:
        """
        An intention was added to the set of intentions.
        """


class UserInterfaceFactory(Protocol):
    """
    Entry point to a frontend that creates a user interface from a user model
    """

    def __call__(self, model: TheUserModel) -> AnUserInterface:
        ...


@dataclass
class Pomodoro:
    """
    Interval where the user has set an intention and is attempting to do
    something.
    """

    startTime: float
    intention: Intention
    endTime: float | None = None

    intervalType: ClassVar[IntervalType] = IntervalType.Pomodoro


@dataclass
class Break:
    """
    Interval where the user is taking some open-ended time to relax, with no
    specific intention.
    """

    startTime: float
    endTime: float
    intervalType: ClassVar[IntervalType] = IntervalType.Break


@dataclass
class GracePeriod:
    """
    Interval where the user is taking some time to set the intention before the
    next Pomodoro interval gets started.
    """

    startTime: float
    endTime: float
    intervalType: ClassVar[IntervalType] = IntervalType.GracePeriod


MaybeFloat = TypeVar("MaybeFloat", float, None)


@dataclass
class Estimate:
    """
    An estimation of how long a given task will take, as well as the amount of
    time already spent on it.
    """

    original: float
    """
    The original estimate, in seconds.
    """
    elapsed: float
    """
    The amount of time elapsed on this estimate thus far, in seconds.
    """


@dataclass
class Intention(Generic[MaybeFloat]):
    """
    An intention of something to do.
    """

    model: TheUserModel
    description: str
    estimate: Estimate | None


AnyInterval = Pomodoro | Break | GracePeriod


class IntentionSuccess(Enum):
    Achieved = "Achieved"
    "The goal described in the intention is finished."
    Focused = "Focused"
    "Good focus during the pomodoro, but the goal was not complete."
    Distracted = "Distracted"
    "Distracted during the pomodoro; not great progress."


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


@dataclass
class IntentionScore:
    """
    Setting an intention gives a point.
    """

    intention: Intention
    time: float
    points: int = 1


x: type[ScoreEvent] = IntentionScore


@dataclass
class EvaluationScore:
    """
    Evaluating an intention gives a point.
    """

    time: float
    points: int = 1


x = EvaluationScore


@dataclass
class TheUserModel:
    """
    Model of the user's ongoing pomodoro experience.
    """

    _initialTime: float
    _interfaceFactory: UserInterfaceFactory
    _intentions: list[Intention] = field(default_factory=list)
    _intervals: list[AnyInterval] = field(default_factory=list)
    _score: list[ScoreEvent] = field(default_factory=list)
    _lastUpdateTime: float = field(init=False)
    _userInterface: AnUserInterface | None = None
    # TODO: rollup of previous intentions / intervals for comparison so we
    # don't need to keep all of history in memory at all times

    def __post_init__(self) -> None:
        self.advanceToTime(self._initialTime)

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

    def nextInflectionPoint(self) -> float | None:
        """
        Get the next time at which something "interesting" will happen; i.e.
        the time when the current pomodoro will end.

        Sometimes there are no pending interesting events, in which case it
        will return None.
        """
        # TODO: implement

    def advanceToTime(self, newTime: float) -> None:
        """
        Advance to the epoch time given.
        """
        self._lastUpdateTime = newTime
        # Question: do I want to float the time to float?
        # TODO: implement the time to advance to!!

    def addIntention(
        self, description: str, estimation: float | None
    ) -> Intention:
        """
        Add an intention with the given description and time estimate.
        """
        self._intentions.append(
            newIntention := Intention(
                self,
                description,
                None
                if estimation is None
                else Estimate(estimation, estimation),
            )
        )
        self.userInterface.intentionAdded(newIntention)
        return newIntention

    def startPomodoro(self, intention: Intention) -> Pomodoro:
        """
        When you start a pomodoro, the length of time set by the pomodoro is
        determined by your current streak so it's not a parameter.
        """
        self.userInterface.intervalStart(IntervalType.Pomodoro)
        self._intervals.append(
            pomodoro := Pomodoro(
                startTime=self._lastUpdateTime,
                intention=intention,
            )
        )
        return pomodoro

    def evaluatePomodoro(
        self, pomodoro: Pomodoro, success: IntentionSuccess
    ) -> None:
        """
        The user has determined the success criteria.
        """
        # TODO: implement
