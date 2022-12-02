"""
General-purpose PyObjC utilities that might belong in a different package.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from Foundation import NSCalendar, NSCalendarUnitDay, NSCalendarUnitHour, NSCalendarUnitMinute, NSCalendarUnitMonth, NSCalendarUnitNanosecond, NSCalendarUnitSecond, NSCalendarUnitYear, NSDate

from .quickapp import Actionable
from AppKit import NSNotificationCenter
from dateutil.tz import tzlocal


@dataclass
class Remover:
    center: NSNotificationCenter
    name: str
    observer: object
    sender: object

    def removeObserver(self) -> None:
        self.center.removeObserver_name_object_(self.observer, self.name, self.sender)


def callOnNotification(nsNotificationName: str, f: Callable[[], None]) -> Remover:
    """
    When the given notification occurs, call the given callable with no
    arguments.
    """
    defaultCenter = NSNotificationCenter.defaultCenter()
    observer = Actionable.alloc().initWithFunction_(f)
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
