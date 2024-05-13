# -*- test-case-name: pomodouroboros.model.test.test_util -*-
from __future__ import annotations

from contextlib import contextmanager
from functools import wraps
from typing import (
    Callable,
    Concatenate,
    Iterator,
    Literal,
    ParamSpec,
    Protocol,
    TypeVar,
)

from dateutil.relativedelta import relativedelta
from twisted.python.failure import Failure

from .debugger import debug
from .nexus import Nexus
from .storage import saveDefaultNexus

T = TypeVar("T")


def intervalSummary(seconds: int) -> str:
    """
    Produce a human-readable summary for a number of seconds.
    """
    delta = relativedelta(seconds=seconds)
    segments = [
        "%d %s" % (value, attr if value > 1 else attr[:-1])
        for attr in [
            "years",
            "months",
            "days",
            "hours",
            "minutes",
            "seconds",
        ]
        if (value := getattr(delta, attr))
    ]
    if not segments:
        segments = ["0 seconds"]
    if len(segments) > 1:
        segments[-2:] = [f"{segments[-2]} and {segments[-1]}"]
    return ", ".join(segments)


@contextmanager
def showFailures() -> Iterator[None]:
    """
    Print a traceback to stdout if the wrapped operation fails.

    (Some GUI libraries don't do a great job of showing you errors, so this
    forces the reporting to be synchronous.)
    """
    try:
        yield
    except:
        print(Failure().getTraceback())
        raise


class HasNexus(Protocol):
    nexus: Nexus


C = TypeVar("C", bound=Callable[..., object])
P = ParamSpec("P")
HN = TypeVar("HN", bound=HasNexus)


def interactionRoot(
    c: Callable[Concatenate[HN, P], T]
) -> Callable[Concatenate[HN, P], T]:
    """
    Decorator that should wrap every operation that potentially mutates the
    model, saving it back to disk afterwards if it completes without raising an
    exception, or printing the exception to the terminal if it does raise one.
    """

    @wraps(c)
    def showFailuresAndSave(self: HN, *args: P.args, **kwargs: P.kwargs) -> T:
        # idea: maybe maintain a trail of N backups here, for easy undo/revert
        # of certain edit actions?
        with showFailures():
            debug("start action:", c)
            result = c(self, *args, **kwargs)
            debug("save nexus:", result)
            saveDefaultNexus(self.nexus)
            debug("saved:", result)
            return result

    return showFailuresAndSave


AMPM = Literal["AM", "PM"]


def ampmify(hour: int, ampm: AMPM) -> int:
    if hour < 1 or hour > 12:
        raise ValueError(f"{hour} out of range 0-24")
    if hour == 12:
        if ampm == "AM":
            return 0
        else:
            return 12
    elif ampm == "PM":
        return hour + 12
    else:
        return hour


def addampm(hour: int) -> tuple[int, AMPM]:
    if hour < 0 or hour > 24:
        raise ValueError(f"{hour} out of range 0-24")
    if hour == 0:
        return (12, "AM")
    elif hour == 12:
        return (12, "PM")
    elif hour > 12:
        return (hour - 12, "PM")
    else:
        return (hour, "AM")
