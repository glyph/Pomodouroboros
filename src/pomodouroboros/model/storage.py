# -*- test-case-name: pomodouroboros -*-

from __future__ import annotations

from functools import singledispatch
from os import makedirs
from typing import Literal, TypeAlias, TypedDict, Union, cast

from .boundaries import IntervalType, UserInterfaceFactory
from .intention import Estimate, Intention
from .intervals import AnyInterval, Break, Duration, GracePeriod, Pomodoro, Session, StartPrompt
from .nexus import Nexus


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
        "modified": float,
        "description": str,
        "estimates": list[SavedEstimate],
        # "pomodoros": list[SavedPomodoroID],
        # Pomodoros are ommitted here because it is an invariant they must
        # exclusively appear in this list in the order that they are referenced
        # in the pomodoros themselves, so we can reconstitute that list while
        # loading them.
        "abandoned": bool,
        "title": str,
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
        "pointsBeforeLoss": float,
        "pointsAfterLoss": float,
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


def nexusFromJSON(
    saved: SavedNexus, userInterfaceFactory: UserInterfaceFactory
) -> Nexus:
    """
    Load a Pomodouroboros Nexus from its saved serialized state.
    """
    intentionIDMap: dict[SavedIntentionID, Intention] = {}
    intentions: list[Intention] = []

    for savedIntention in saved["intentions"]:
        intention = Intention(
            title=savedIntention["title"],
            created=savedIntention["created"],
            modified = savedIntention["modified"],
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
                pointsBeforeLoss=savedInterval["pointsBeforeLoss"],
                pointsAfterLoss=savedInterval["pointsAfterLoss"],
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


def nexusToJSON(nexus: Nexus) -> SavedNexus:
    @singledispatch
    def saveInterval(interval: AnyInterval) -> SavedInterval:
        """
        Save any interval to its paired JSON data structure.
        """
        raise TypeError("unsupported type")

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
            "pointsBeforeLoss": interval.pointsBeforeLoss,
            "pointsAfterLoss": interval.pointsAfterLoss,
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
                "modified": intention.modified,
                "title": intention.title,
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


JSON: TypeAlias = "None | str | float | bool | dict[str, JSON] | list[JSON] | SavedNexus"

from os.path import join, dirname, expanduser, exists
from json import dump, load
from os import replace


def saveToFile(filename: str, jsonObject: JSON) -> None:
    """
    Save the given JSON object to a file.
    """
    newp = join(dirname(filename), ".temporary-" + filename + ".new")
    with open(newp, "w") as new:
        dump(jsonObject, new)
    replace(newp, filename)


def loadFromFile(filename: str) -> JSON:
    with open(filename) as f:
        result: JSON = load(f)
        return result

defaultNexusFile = expanduser("~/.local/share/pomodouroboros/current-nexus.json")

def loadDefaultNexus(
    currentTime: float,
    userInterfaceFactory: UserInterfaceFactory,
) -> Nexus:
    """
    Load the default nexus.
    """
    if exists(defaultNexusFile):
        # TODO: probably need to be extremely careful before shipping to
        # end-users here, since failing to create a nexus makes the app
        # unlaunchable
        loaded = nexusFromJSON(
            cast(
                SavedNexus,
                loadFromFile(
                    defaultNexusFile
                ),
            ),
            userInterfaceFactory,
        )
        loaded.advanceToTime(currentTime)
        return loaded
    return Nexus(currentTime, userInterfaceFactory)

def saveDefaultNexus(nexus: Nexus) -> None:
    """
    Save a given nexus to the default file for the current user.
    """
    makedirs(dirname(defaultNexusFile), exist_ok=True)
    saveToFile(defaultNexusFile, nexusToJSON(nexus))
