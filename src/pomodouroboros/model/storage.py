# -*- test-case-name: pomodouroboros -*-

from __future__ import annotations

from functools import singledispatch
from json import dump, load
from os import makedirs, replace
from os.path import basename, dirname, exists, expanduser, join
from typing import TypeAlias, cast

from .boundaries import EvaluationResult, IntervalType, UserInterfaceFactory
from .intention import Estimate, Intention
from .intervals import (
    AnyStreakInterval,
    Break,
    Duration,
    Evaluation,
    GracePeriod,
    Pomodoro,
    StartPrompt,
)
from .nexus import Nexus
from .observables import IgnoreChanges, ObservableList
from .schema import (
    SavedBreak,
    SavedGracePeriod,
    SavedIntentionID,
    SavedInterval,
    SavedNexus,
    SavedPomodoro,
    SavedStartPrompt,
)
from .sessions import Session


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
            id=int(savedIntention["id"]),
            title=savedIntention["title"],
            created=savedIntention["created"],
            modified=savedIntention["modified"],
            description=savedIntention["description"],
            abandoned=savedIntention["abandoned"],
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

    def loadInterval(savedInterval: SavedInterval) -> AnyStreakInterval:
        if savedInterval["intervalType"] == "Pomodoro":
            intention = intentionIDMap[savedInterval["intentionID"]]
            evaluation = savedInterval["evaluation"]
            pomodoro = Pomodoro(
                startTime=savedInterval["startTime"],
                intention=intention,
                endTime=savedInterval["endTime"],
                indexInStreak=savedInterval["indexInStreak"],
                evaluation=(
                    Evaluation(
                        EvaluationResult(evaluation["result"]),
                        evaluation["timestamp"],
                    )
                    if evaluation is not None
                    else None
                ),
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

    previousStreaks = [
        [loadInterval(interval) for interval in savedStreak]
        for savedStreak in saved["previousStreaks"]
    ]
    currentStreak = [
        loadInterval(interval) for interval in saved["currentStreak"]
    ]

    nexus = Nexus(
        _lastIntentionID=int(saved["lastIntentionID"]),
        _intentions=intentions,
        _upcomingDurations=iter(
            [
                Duration(
                    IntervalType(each["intervalType"]), seconds=each["seconds"]
                )
                for each in saved["upcomingDurations"]
            ]
        ),
        _previousStreaks=previousStreaks,
        _currentStreak=currentStreak,
        _sessions=ObservableList(
            IgnoreChanges,
            [
                Session(
                    start=each["start"],
                    end=each["end"],
                    automatic=bool(each.get("automatic")),
                )
                for each in saved["sessions"]
            ],
        ),
        _interfaceFactory=userInterfaceFactory,
        _lastUpdateTime=saved["lastUpdateTime"],
    )
    return nexus


def nexusToJSON(nexus: Nexus) -> SavedNexus:
    @singledispatch
    def saveInterval(interval: AnyStreakInterval) -> SavedInterval:
        """
        Save any interval to its paired JSON data structure.
        """
        raise TypeError("unsupported type")

    @saveInterval.register(Pomodoro)
    def savePomodoro(interval: Pomodoro) -> SavedPomodoro:
        return {
            "startTime": interval.startTime,
            "intentionID": str(interval.intention.id),
            "endTime": interval.endTime,
            "evaluation": (
                {
                    "result": interval.evaluation.result.value,
                    "timestamp": interval.evaluation.timestamp,
                }
                if interval.evaluation is not None
                else None
            ),
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

    return {
        "lastIntentionID": str(nexus._lastIntentionID),
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
                "id": str(intention.id),
            }
            for intention in nexus._intentions
        ],
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
        "currentStreak": [
            saveInterval(streakInterval)
            for streakInterval in nexus._currentStreak
        ],
        "previousStreaks": [
            [
                saveInterval(streakInterval)
                for streakInterval in streakIntervals
            ]
            for streakIntervals in nexus._previousStreaks
        ],
        "sessions": [
            {
                "start": session.start,
                "end": session.end,
                "automatic": session.automatic,
            }
            for session in nexus._sessions
        ],
    }


JSON: TypeAlias = (
    "None | str | float | bool | dict[str, JSON] | list[JSON] | SavedNexus"
)


def saveToFile(filename: str, jsonObject: JSON) -> None:
    """
    Save the given JSON object to a file.
    """
    newp = join(dirname(filename), ".temporary-" + basename(filename) + ".new")
    with open(newp, "w") as new:
        dump(jsonObject, new)
    replace(newp, filename)


def loadFromFile(filename: str) -> JSON:
    with open(filename) as f:
        result: JSON = load(f)
        return result


defaultNexusFile = expanduser(
    "~/.local/share/pomodouroboros/current-nexus.json"
)


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
                loadFromFile(defaultNexusFile),
            ),
            userInterfaceFactory,
        )
        loaded.advanceToTime(currentTime)
        return loaded
    return Nexus(userInterfaceFactory, 0)


def saveDefaultNexus(nexus: Nexus) -> None:
    """
    Save a given nexus to the default file for the current user.
    """
    makedirs(dirname(defaultNexusFile), exist_ok=True)
    saveToFile(defaultNexusFile, nexusToJSON(nexus))
