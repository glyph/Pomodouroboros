"""
General-purpose PyObjC utilities that might belong in a different package.
"""

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Iterator

from AppKit import (
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
)
from dateutil.tz import tzlocal
from quickmacapp import Actionable
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


