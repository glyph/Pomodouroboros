from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Callable, Protocol, TypeAlias

from ..model.observables import Changes, IgnoreChanges, SequenceObserver

if TYPE_CHECKING:
    from .intention import Estimate, Intention
    from .intervals import AnyIntervalOrIdle, Pomodoro
    from .nexus import Nexus


class IntervalType(Enum):
    """
    The type of a given interval.
    """

    Pomodoro = "Pomodoro"
    GracePeriod = "GracePeriod"
    Break = "Break"
    StartPrompt = "StartPrompt"
    Idle = "Idle"


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


class UIEventListener(Protocol):
    """
    The user interface must implement all intention and interval methods.
    """

    def describeCurrentState(self, description: str) -> None:
        """
        Describe the current state to the user with the given description string.
        """

    def intervalStart(self, interval: AnyIntervalOrIdle) -> None:
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

    def intentionListObserver(self) -> SequenceObserver[Intention]:
        """
        Return a change observer for the full list of L{Intention}s.
        """

    def intentionObjectObserver(
        self, intention: Intention
    ) -> Changes[str, object]:
        """
        Return a change observer for the given L{Intention}.
        """

    def intentionPomodorosObserver(
        self, intention: Intention
    ) -> SequenceObserver[Pomodoro]:
        """
        Return a change observer for the given L{Intention}'s list of
        pomodoros.
        """

    def intentionEstimatesObserver(
        self, intention: Intention
    ) -> SequenceObserver[Estimate]:
        """
        Return a change observer for the given L{Intention}'s list of
        estimates.
        """

    def intervalObserver(self, interval: AnyIntervalOrIdle) -> Changes[str, object]:
        """
        Return a change observer for the given C{interval}.
        """


@dataclass
class NoUserInterface(UIEventListener):
    """
    Do-nothing implementation of a user interface.
    """

    def describeCurrentState(self, description: str) -> None:
        ...

    def intervalStart(self, interval: AnyIntervalOrIdle) -> None:
        ...

    def intervalProgress(self, percentComplete: float) -> None:
        ...

    def intervalEnd(self) -> None:
        ...

    def intentionListObserver(self) -> SequenceObserver[Intention]:
        """
        Return a change observer for the full list of L{Intention}s.
        """
        return IgnoreChanges

    def intentionObjectObserver(
        self, intention: Intention
    ) -> Changes[str, object]:
        """
        Return a change observer for the given L{Intention}.
        """
        return IgnoreChanges

    def intentionPomodorosObserver(
        self, intention: Intention
    ) -> SequenceObserver[Pomodoro]:
        """
        Return a change observer for the given L{Intention}'s list of
        pomodoros.
        """
        return IgnoreChanges

    def intentionEstimatesObserver(
        self, intention: Intention
    ) -> SequenceObserver[Estimate]:
        """
        Return a change observer for the given L{Intention}'s list of
        estimates.
        """
        return IgnoreChanges

    def intervalObserver(self, interval: AnyIntervalOrIdle) -> Changes[str, object]:
        """
        Return a change observer for the given C{interval}.
        """
        return IgnoreChanges


# Not a protocol because https://github.com/python/mypy/issues/14544
UserInterfaceFactory: TypeAlias = "Callable[[Nexus], UIEventListener]"


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
