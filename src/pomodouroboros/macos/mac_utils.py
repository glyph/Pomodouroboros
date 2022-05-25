"""
General-purpose PyObjC utilities that might belong in a different package.
"""

from typing import Callable

from datetime import datetime
from dateutil.tz import tzlocal

from Foundation import (
    NSCalendarUnitYear,
    NSCalendarUnitMonth,
    NSCalendarUnitDay,
    NSCalendarUnitHour,
    NSCalendarUnitMinute,
    NSCalendarUnitSecond,
    NSCalendarUnitNanosecond,
    NSCalendar,
    NSDate,
)
from Foundation import NSCalendar, NSDate

from AppKit import NSNotificationCenter

from .quickapp import Actionable


def callOnNotification(nsNotificationName: str, f: Callable[[], None]) -> None:
    NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
        Actionable.alloc().initWithFunction_(f).retain(),
        "doIt:",
        nsNotificationName,
        None,
    )


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
