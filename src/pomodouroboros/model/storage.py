# -*- test-case-name: pomodouroboros -*-

from __future__ import annotations

from functools import singledispatch
from json import dump, load
from os import makedirs, replace
from os.path import basename, dirname, exists, expanduser, join
from typing import TypeAlias, cast

from pomodouroboros.model.boundaries import EvaluationResult
from pomodouroboros.model.observables import IgnoreChanges, ObservableList
from pomodouroboros.model.sessions import Session

from .boundaries import IntervalType, UserInterfaceFactory
from .intention import Estimate, Intention
from .intervals import (
    AnyInterval,
    Break,
    Duration,
    Evaluation,
    GracePeriod,
    Pomodoro,
    StartPrompt,
)
from .nexus import Nexus
from .schema import (
    SavedBreak,
    SavedGracePeriod,
    SavedIntentionID,
    SavedInterval,
    SavedNexus,
    SavedPomodoro,
    SavedStartPrompt,
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

    def loadInterval(savedInterval: SavedInterval) -> AnyInterval:
        if savedInterval["intervalType"] == "Pomodoro":
            intention = intentionIDMap[savedInterval["intentionID"]]
            evaluation = savedInterval["evaluation"]
            pomodoro = Pomodoro(
                startTime=savedInterval["startTime"],
                intention=intention,
                endTime=savedInterval["endTime"],
                indexInStreak=savedInterval["indexInStreak"],
                evaluation=Evaluation(
                    EvaluationResult(evaluation["result"]),
                    evaluation["timestamp"],
                )
                if evaluation is not None
                else None,
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

    streaks = ObservableList(
        IgnoreChanges,
        [
            ObservableList(
                IgnoreChanges,
                [loadInterval(interval) for interval in savedStreak],
            )
            for savedStreak in saved["streaks"]
        ],
    )
    nexus = Nexus(
        _lastIntentionID=int(saved["lastIntentionID"]),
        _initialTime=saved["initialTime"],
        _intentions=intentions,
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
    def saveInterval(interval: AnyInterval) -> SavedInterval:
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

    return {
        "initialTime": nexus._initialTime,
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
        "streaks": [
            [
                saveInterval(streakInterval)
                for streakInterval in streakIntervals
            ]
            for streakIntervals in nexus._streaks
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
    return Nexus(currentTime, userInterfaceFactory, 0)


def saveDefaultNexus(nexus: Nexus) -> None:
    """
    Save a given nexus to the default file for the current user.
    """
    makedirs(dirname(defaultNexusFile), exist_ok=True)
    saveToFile(defaultNexusFile, nexusToJSON(nexus))
