"""
General-purpose PyObjC utilities that might belong in a different package.
"""

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Iterable, Iterator

from AppKit import (
    NSAlertFirstButtonReturn,
    NSAlertSecondButtonReturn,
    NSAlertThirdButtonReturn,
    NSAlert,
    NSApp,
    NSNotificationCenter,
)
from Foundation import (
    NSCalendar,
    NSCalendarUnitDay,
    NSCalendarUnitHour,
    NSCalendarUnitMinute,
    NSCalendarUnitMonth,
    NSCalendarUnitNanosecond,
    NSCalendarUnitSecond,
    NSCalendarUnitYear,
    NSDate,
    NSObject,
    NSRunLoop,
    NSTextField,
    NSView,
    NSRect,
)
from dateutil.tz import tzlocal
from quickmacapp import Actionable
from twisted.internet.defer import Deferred
from twisted.python.failure import Failure


@dataclass
class Remover:
    center: NSNotificationCenter
    name: str
    observer: NSObject
    sender: NSObject | None

    def removeObserver(self) -> None:
        # lifecycle management: paired with observer.retain() in callOnNotification
        self.observer.release()
        if self.sender is not None:
            # Unused, but lifecycle management would demand sender be retained
            # by any observer-adding code as well.
            self.sender.release()
        self.center.removeObserver_name_object_(
            self.observer,
            self.name,
        )


def callOnNotification(
    nsNotificationName: str, f: Callable[[], None]
) -> Remover:
    """
    When the given notification occurs, call the given callable with no
    arguments.
    """
    defaultCenter = NSNotificationCenter.defaultCenter()
    observer = Actionable.alloc().initWithFunction_(f)
    # lifecycle management: paired with the observer.release() in releaser
    observer.retain()
    sender = None
    defaultCenter.addObserver_selector_name_object_(
        observer,
        "doIt:",
        nsNotificationName,
        sender,
    )
    return Remover(defaultCenter, nsNotificationName, observer, sender)


fromDate = NSCalendar.currentCalendar().components_fromDate_
localOffset = tzlocal()
nsDateNow = NSDate.date
nsDateFromTimestamp = NSDate.dateWithTimeIntervalSince1970_

datetimeComponents = (
    NSCalendarUnitYear
    | NSCalendarUnitMonth
    | NSCalendarUnitDay
    | NSCalendarUnitHour
    | NSCalendarUnitMinute
    | NSCalendarUnitSecond
    | NSCalendarUnitNanosecond
)


def datetimeFromNSDate(nsdate: NSDate) -> datetime:
    """
    Convert an NSDate to a Python datetime.
    """
    components = fromDate(datetimeComponents, nsdate)
    return datetime(
        year=components.year(),
        month=components.month(),
        day=components.day(),
        hour=components.hour(),
        minute=components.minute(),
        second=components.second(),
        microsecond=components.nanosecond() // 1000,
        tzinfo=localOffset,
    )


def localDate(ts: float) -> datetime:
    """
    Use Cocoa to compute a local datetime
    """
    return datetimeFromNSDate(nsDateFromTimestamp(ts))


@contextmanager
def showFailures() -> Iterator[None]:
    """
    show failures and stuff
    """
    try:
        yield
    except:
        print(Failure().getTraceback())
        raise


NSModalResponse = int


def asyncModal(alert: NSAlert) -> Deferred[NSModalResponse]:
    """
    Run an NSAlert asynchronously.
    """
    d: Deferred[NSModalResponse] = Deferred()

    def runAndReport() -> None:
        try:
            NSApp().activateIgnoringOtherApps_(True)
            result = alert.runModal()
        except:
            d.errback()
        else:
            d.callback(result)

    NSRunLoop.currentRunLoop().performBlock_(runAndReport)
    return d


from typing import TypeVar

T = TypeVar("T")


def _alertReturns() -> Iterator[NSModalResponse]:
    """
    Enumerate the values used by NSAlert for return values in the order of the
    buttons that occur.
    """
    yield NSAlertFirstButtonReturn
    yield NSAlertSecondButtonReturn
    yield NSAlertThirdButtonReturn
    i = 1
    while True:
        yield NSAlertThirdButtonReturn + i
        i += 1


async def getChoice(
    title: str, description: str, values: Iterable[tuple[T, str]]
) -> T:
    """
    Allow the user to choose between the given values, on buttons labeled in
    the given way.
    """
    msg = NSAlert.alloc().init()
    msg.setMessageText_(title)
    msg.setInformativeText_(description)
    potentialResults = {}
    for (value, label), alertReturn in zip(values, _alertReturns()):
        msg.addButtonWithTitle_(label)
        potentialResults[alertReturn] = value
    msg.layout()
    return potentialResults[await asyncModal(msg)]


async def getString(
    title: str, question: str, defaultValue: str
) -> str | None:
    """
    Prompt the user for some text.
    """
    msg = NSAlert.alloc().init()
    msg.addButtonWithTitle_("OK")
    msg.addButtonWithTitle_("Cancel")
    msg.setMessageText_(title)
    msg.setInformativeText_(question)

    txt = NSTextField.alloc().initWithFrame_(NSRect((0, 0), (200, 100)))
    txt.setMaximumNumberOfLines_(5)
    txt.setStringValue_(defaultValue)
    msg.setAccessoryView_(txt)
    msg.window().setInitialFirstResponder_(txt)
    msg.layout()
    NSApp().activateIgnoringOtherApps_(True)

    response: NSModalResponse = await asyncModal(msg)

    if response == NSAlertFirstButtonReturn:
        result: str = txt.stringValue()
        return result

    return None
