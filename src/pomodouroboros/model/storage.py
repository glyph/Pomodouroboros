from __future__ import annotations

from functools import singledispatch
from typing import Literal, TypedDict, Union

from .boundaries import UserInterfaceFactory, IntervalType
from .intervals import (
    AnyInterval,
    Pomodoro,
    Break,
    Duration,
    GracePeriod,
    Session,
    StartPrompt,
)
from .nexus import Nexus
from .intention import Estimate, Intention


SavedIntervalType = Literal["Pomodoro", "GracePeriod", "Break", "StartPrompt"]
SavedEstimate = TypedDict(
    "SavedEstimate",
    {
        "duration": float,
        "madeAt": float,
    },
)
SavedPomodoroID = str
SavedIntentionID = str

SavedIntention = TypedDict(
    "SavedIntention",
    {
        "created": float,
        "description": str,
        "estimates": list[SavedEstimate],
        # "pomodoros": list[SavedPomodoroID],
        # Pomodoros are ommitted here because it is an invariant they must
        # exclusively appear in this list in the order that they are referenced
        # in the pomodoros themselves, so we can reconstitute that list while
        # loading them.
        "abandoned": bool,
        "id": SavedIntentionID,
    },
)

SavedBreak = TypedDict(
    "SavedBreak",
    {
        "startTime": float,
        "endTime": float,
        "intervalType": Literal["Break"],
    },
)
SavedEvaluationResult = Literal[
    "distracted", "interrupted", "focused", "achieved"
]
SavedEvaluation = TypedDict(
    "SavedEvaluation",
    {
        "result": SavedEvaluationResult,
        "timestamp": float,
    },
)
SavedPomodoro = TypedDict(
    "SavedPomodoro",
    {
        "startTime": float,
        "intentionID": SavedIntentionID,
        "endTime": float,
        "evaluation": SavedEvaluation | None,
        "indexInStreak": int,
        "intervalType": Literal["Pomodoro"],
    },
)

SavedGracePeriod = TypedDict(
    "SavedGracePeriod",
    {
        "startTime": float,
        "originalPomEnd": float,
        "intervalType": Literal["GracePeriod"],
    },
)

SavedStartPrompt = TypedDict(
    "SavedStartPrompt",
    {
        "startTime": float,
        "endTime": float,
        "pointsLost": float,
        "intervalType": Literal["StartPrompt"],
    },
)
SavedSession = TypedDict("SavedSession", {"start": float, "end": float})

SavedInterval = Union[
    SavedPomodoro, SavedBreak, SavedGracePeriod, SavedStartPrompt
]
SavedDuration = TypedDict(
    "SavedDuration", {"intervalType": SavedIntervalType, "seconds": float}
)
SavedStreak = list[SavedInterval]

SavedNexus = TypedDict(
    "SavedNexus",
    {
        "initialTime": float,
        "intentions": list[SavedIntention],
        "intervalIsActive": bool,
        "lastUpdateTime": float,
        "upcomingDurations": list[SavedDuration],
        "streaks": list[SavedStreak],
        "sessions": list[SavedSession],
    },
)


def loadNexus(
    saved: SavedNexus, userInterfaceFactory: UserInterfaceFactory
) -> Nexus:
    """
    Load a Pomodouroboros Nexus from its saved serialized state.
    """
    intentionIDMap: dict[SavedIntentionID, Intention] = {}
    intentions: list[Intention] = []

    for savedIntention in saved["intentions"]:
        intention = Intention(
            created=savedIntention["created"],
            description=savedIntention["description"],
            estimates=[
                Estimate(
                    duration=savedEstimate["duration"],
                    madeAt=savedEstimate["madeAt"],
                )
                for savedEstimate in savedIntention["estimates"]
            ],
        )
        intentions.append(intention)
        intentionIDMap[savedIntention["id"]] = intention

    def loadInterval(savedInterval: SavedInterval) -> AnyInterval:
        if savedInterval["intervalType"] == "Pomodoro":
            intention = intentionIDMap[savedInterval["intentionID"]]
            pomodoro = Pomodoro(
                startTime=savedInterval["startTime"],
                intention=intention,
                endTime=savedInterval["endTime"],
                indexInStreak=savedInterval["indexInStreak"],
            )
            intention.pomodoros.append(pomodoro)
            return pomodoro
        elif savedInterval["intervalType"] == "StartPrompt":
            return StartPrompt(
                startTime=savedInterval["startTime"],
                endTime=savedInterval["endTime"],
                pointsLost=savedInterval["pointsLost"],
            )
        elif savedInterval["intervalType"] == "Break":
            return Break(
                startTime=savedInterval["startTime"],
                endTime=savedInterval["endTime"],
            )
        elif savedInterval["intervalType"] == "GracePeriod":
            return GracePeriod(
                startTime=savedInterval["startTime"],
                originalPomEnd=savedInterval["originalPomEnd"],
            )

    streaks = [
        [loadInterval(interval) for interval in savedStreak]
        for savedStreak in saved["streaks"]
    ]
    activeInterval = (
        streaks[-1][-1] if saved["intervalIsActive"] is not None else None
    )
    nexus = Nexus(
        _initialTime=saved["initialTime"],
        _intentions=intentions,
        _activeInterval=activeInterval,
        # lastUpdateTime below. maybe it should not be init=False
        _upcomingDurations=iter(
            [
                Duration(
                    IntervalType(each["intervalType"]), seconds=each["seconds"]
                )
                for each in saved["upcomingDurations"]
            ]
        ),
        _streaks=streaks,
        _sessions=[
            Session(start=each["start"], end=each["end"])
            for each in saved["sessions"]
        ],
        _interfaceFactory=userInterfaceFactory,
    )
    nexus._lastUpdateTime = saved["lastUpdateTime"]
    return nexus


def asJSON(nexus: Nexus) -> SavedNexus:
    @singledispatch
    def saveInterval(interval: AnyInterval) -> SavedInterval:
        """
        Save any interval to its paired JSON data structure.
        """

    @saveInterval.register(Pomodoro)
    def savePomodoro(interval: Pomodoro) -> SavedPomodoro:
        return {
            "startTime": interval.startTime,
            "intentionID": str(id(interval.intention)),
            "endTime": interval.endTime,
            "evaluation": {
                "result": interval.evaluation.result.value,
                "timestamp": interval.evaluation.timestamp,
            }
            if interval.evaluation is not None
            else None,
            "indexInStreak": interval.indexInStreak,
            "intervalType": "Pomodoro",
        }

    @saveInterval.register(Break)
    def saveBreak(interval: Break) -> SavedBreak:
        return {
            "startTime": interval.startTime,
            "endTime": interval.endTime,
            "intervalType": "Break",
        }

    @saveInterval.register(GracePeriod)
    def saveGracePeriod(interval: GracePeriod) -> SavedGracePeriod:
        return {
            "startTime": interval.startTime,
            "originalPomEnd": interval.originalPomEnd,
            "intervalType": "GracePeriod",
        }

    @saveInterval.register(StartPrompt)
    def saveStartPrompt(interval: StartPrompt) -> SavedStartPrompt:
        return {
            "startTime": interval.startTime,
            "endTime": interval.endTime,
            "pointsLost": interval.pointsLost,
            "intervalType": "StartPrompt",
        }

    intervalIsActive = nexus._activeInterval is not None
    assert (not intervalIsActive) or (
        nexus._activeInterval is nexus._streaks[-1][-1]
    ), (
        "active interval should always be the most recent interval "
        "on the most recent streak"
    )

    return {
        "initialTime": nexus._initialTime,
        "intentions": [
            {
                "created": intention.created,
                "description": intention.description,
                "estimates": [
                    {"duration": estimate.duration, "madeAt": estimate.madeAt}
                    for estimate in intention.estimates
                ],
                "abandoned": intention.abandoned,
                "id": str(id(intention)),
            }
            for intention in nexus._intentions
        ],
        "intervalIsActive": intervalIsActive,
        "lastUpdateTime": nexus._lastUpdateTime,
        "upcomingDurations": [
            {
                "intervalType": duration.intervalType.value,
                "seconds": duration.seconds,
            }
            # TODO: slightly inefficient, don't clone the whole thing just to
            # clone the iterator
            for duration in nexus.cloneWithoutUI()._upcomingDurations
        ],
        "streaks": [
            [
                saveInterval(streakInterval)
                for streakInterval in streakIntervals
            ]
            for streakIntervals in nexus._streaks
        ],
        "sessions": [
            {"start": session.start, "end": session.end}
            for session in nexus._sessions
        ],
    }
