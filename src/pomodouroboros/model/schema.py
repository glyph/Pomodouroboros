from typing import Literal, TypedDict, Union

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
SavedSession = TypedDict(
    "SavedSession", {"start": float, "end": float, "automatic": bool}
)

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
        "lastIntentionID": str,
        "initialTime": float,
        "intentions": list[SavedIntention],
        "lastUpdateTime": float,
        "upcomingDurations": list[SavedDuration],
        "streaks": list[SavedStreak],
        "sessions": list[SavedSession],
    },
)
