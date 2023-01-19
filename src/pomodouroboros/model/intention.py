from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, ClassVar, Iterable


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

    def intentionScoreEvents(
        self, intentionIndex: int
    ) -> Iterable[ScoreEvent]:
        yield IntentionCreatedEvent(self, intentionIndex)
        for estimate, _ in zip(self.estimates, range(len(self.pomodoros) + 1)):
            # Only give a point for one estimation per attempt; estimating is
            # good, but correcting more than once per work session is just
            # faffing around
            yield AttemptedEstimation(estimate)
        if self.completed:
            yield IntentionCompleted(self)
            if self.estimates:
                yield EstimationAccuracy(self)


# Circular imports
from pomodouroboros.model.boundaries import (
    EvaluationResult,
    IntervalType,
    PomStartResult,
    ScoreEvent,
)

from pomodouroboros.model.intervals import Pomodoro
from pomodouroboros.model.nexus import TheUserModel
from pomodouroboros.model.scoring import (
    AttemptedEstimation,
    BreakCompleted,
    EstimationAccuracy,
    IntentionCompleted,
    IntentionCreatedEvent,
)
