from __future__ import annotations
from typing import TYPE_CHECKING
from dataclasses import dataclass, field

from .boundaries import ScoreEvent

if TYPE_CHECKING:
    from .intervals import Break
    from .intention import Estimate, Intention


_is_score_event: type[ScoreEvent]


@dataclass
class IntentionCreatedEvent:
    """
    You get points for creating intentions.
    """

    intention: Intention
    intentionIndex: int

    @property
    def time(self) -> float:
        return self.intention.created

    @property
    def points(self) -> int:
        """
        Creating intentions is good, but there are diminishing returns.  The
        first 3 intentions will give you 3 points each, the next 3 will give
        you 2 points, and the next 3 will give you 1 point each.  Every
        intention after the 9th one is worth 0 points.
        """
        # >>> [max(0, 3-(x//3)) for x in range(15)]
        # [3, 3, 3, 2, 2, 2, 1, 1, 1, 0, 0, 0, 0, 0, 0]
        return max(0, 3 - (self.intentionIndex // 3))


_is_score_event = IntentionCreatedEvent


@dataclass
class IntentionCompleted:
    intention: Intention

    @property
    def time(self) -> float:
        evaluation = self.intention.pomodoros[-1].evaluation
        assert evaluation is not None
        return evaluation.timestamp

    @property
    def points(self) -> int:
        """
        When an intention is completed, the user is given 10 points.  This can
        be given two additional bonuses: if it took more than 1 pomodoro to
        finish, 1 additional point per pomodoro will be granted, up to 5 pomodoros.
        """
        score = 10
        score += min(5, (len(self.intention.pomodoros) - 1))
        return score


_is_score_event = IntentionCompleted


@dataclass
class BreakCompleted:
    """
    A break being completed gives us one point.
    """

    interval: Break

    @property
    def time(self) -> float:
        return self.interval.endTime

    @property
    def points(self) -> float:
        return 1.0


_is_score_event = BreakCompleted


@dataclass
class EstimationAccuracy:
    intention: Intention

    @property
    def time(self) -> float:
        evaluation = self.intention.pomodoros[-1].evaluation
        assert evaluation is not None
        return evaluation.timestamp

    @property
    def points(self) -> int:
        """
        When an intention is completed, give some points for how close the
        estimate was.
        """
        actualTimeTaken = sum(
            (each.endTime - each.startTime)
            for each in self.intention.pomodoros
        )
        timeOfEvaluation = self.time
        allEstimateScores: list[int] = []
        for estimate, recencyCap in zip(
            self.intention.estimates[-10::-1], range(10, 1, -1)
        ):
            # Counting down from the most recent estimate to the 10th most
            # recent, we give progressively smaller caps to the estimate.
            timeSinceEstimate = timeOfEvaluation - estimate.madeAt
            # You get more points for estimates that are earlier (specifically,
            # you only get max credit for estimates that are made longer ago
            # than the total time that the thing took to do).  This is a rough
            # heuristic, because it's still technically gameable if you have a
            # task that takes a super long time and you have dozens of
            # pomodoros on it, estimate that you only have a single pomdoro
            # left, then wait a day before completing it.
            timeSinceEstimateCap = int(
                min(1.0, timeSinceEstimate / actualTimeTaken) * 10
            )
            # You obviously get more points for having made more accurate estimates.
            distanceSeconds = abs(actualTimeTaken - estimate.duration)
            distanceHours = distanceSeconds / (60 * 60)
            # within 100 hours you can get 10 points, within 90 hours you can
            # get 9, etc
            distanceScore = min(10, int(distanceHours / 10))
            allEstimateScores.append(
                min([distanceScore, timeSinceEstimateCap, recencyCap])
            )
        return max(allEstimateScores)


_is_score_event = EstimationAccuracy


@dataclass
class AttemptedEstimation:
    """
    The user attempted to estimate how long this would take.
    """

    estimate: Estimate

    @property
    def time(self) -> float:
        return self.estimate.madeAt

    @property
    def points(self) -> float:
        return 1.0


_is_score_event = AttemptedEstimation


@dataclass
class IntentionSet:
    """
    An intention was set: i.e. a pomodoro was started.

    @note: contrast with L{IntentionCreatedEvent}; an intention may be I{set}
        multiple times, but it is I{created} only once.
    """

    intention: Intention
    time: float
    duration: float
    streakLength: int
    """
    How long the intention was set for.
    """

    @property
    def points(self) -> float:
        """
        Setting an intention yields 1 point.
        """
        return int(2**self.streakLength)


_is_score_event = IntentionSet


@dataclass
class EvaluationScore:
    """
    Evaluating an intention gives a point.
    """

    time: float
    points: float = field(default=1)


_is_score_event = EvaluationScore
