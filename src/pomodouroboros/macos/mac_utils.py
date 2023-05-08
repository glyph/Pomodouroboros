"""
General-purpose PyObjC utilities that might belong in a different package.
"""

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Iterator, TypeVar

import objc
from AppKit import (
    NSApplication,
    NSApplicationActivateIgnoringOtherApps,
    NSApplicationActivationPolicyAccessory,
    NSApplicationActivationPolicyRegular,
    NSLog,
    NSNotification,
    NSNotificationCenter,
    NSRunningApplication,
    NSWindow,
    NSWindowWillCloseNotification,
    NSWorkspace,
    NSWorkspaceActiveSpaceDidChangeNotification,
    NSWorkspaceApplicationKey,
    NSWorkspaceDidActivateApplicationNotification,
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
    NSLog,
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


T = TypeVar("T")
S = TypeVar("S")


@dataclass
class Forwarder:
    """
    Forward a set of attributes to an original other attribute.

    Use at class scope.
    """

    original: str

    def forwarded(self, name: str) -> Any:
        """
        Create an attribute that will forward to C{name}.

        Returns L{Any} as a type so it can be assigned to an attribute at class
        scope annotated with the appropriate type.
        """
        prop = objc.object_property()

        @prop.getter
        def getter(oself: S) -> Any:
            return getattr(getattr(oself, self.original), name)

        @getter.setter
        def setter(oself: S, value: T) -> None:
            setattr(getattr(oself, self.original), name, value)

        return prop


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


@dataclass
class SometimesBackground:
    """
    An application that is sometimes in the background but has a window that,
    when visible, can own the menubar, become key, etc.  However, when that
    window is closed, we withdraw to the menu bar and continue running in the
    background, as an accessory.
    """

    mainWindow: NSWindow
    onSpaceChange: Callable[[], None]
    currentlyRegular: bool = False
    previouslyActiveApp: NSRunningApplication = field(init=False)

    def someApplicationActivated_(self, notification: Any) -> None:
        NSLog(f"active {notification} {__file__}")
        whichApp = notification.userInfo()[NSWorkspaceApplicationKey]

        if whichApp == NSRunningApplication.currentApplication():
            if self.currentlyRegular:
                NSLog("show editor window")
                self.mainWindow.setIsVisible_(True)
            else:
                NSLog("reactivate workaround")
                self.currentlyRegular = True
                self.previouslyActiveApp.activateWithOptions_(
                    NSApplicationActivateIgnoringOtherApps
                )
                app = NSApplication.sharedApplication()
                app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
                from time import sleep

                sleep(0.1)
                app.activateIgnoringOtherApps_(True)
        else:
            self.previouslyActiveApp = whichApp

    def someSpaceActivated_(self, notification) -> None:
        """
        Sometimes, fullscreen application stop getting the HUD overlay.
        """
        if (
            NSRunningApplication.currentApplication()
            == NSWorkspace.sharedWorkspace().menuBarOwningApplication()
        ):
            NSLog("my space activated, not doing anything")
            return
        NSLog("space activated, closing window")
        self.mainWindow.close()
        self.onSpaceChange()
        NSLog("window closed")

    def someWindowWillClose_(self, notification: NSNotification) -> None:
        """
        The main window that we're observing will close.
        """
        NSLog(f"it's a window {notification}")
        if notification.object() == self.mainWindow:
            NSLog("it's our window; switching to HUD")
            self.currentlyRegular = False
            NSApplication.sharedApplication().setActivationPolicy_(
                NSApplicationActivationPolicyAccessory
            )
        else:
            NSLog("not ours, though")

    def startObserving(self) -> None:
        """
        Attach the various callbacks.
        """
        NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self, "someWindowWillClose:", NSWindowWillCloseNotification, None
        )
        wsnc = NSWorkspace.sharedWorkspace().notificationCenter()

        self.previouslyActiveApp = (
            NSWorkspace.sharedWorkspace().menuBarOwningApplication()
        )

        wsnc.addObserver_selector_name_object_(
            self,
            "someApplicationActivated:",
            NSWorkspaceDidActivateApplicationNotification,
            None,
        )

        wsnc.addObserver_selector_name_object_(
            self,
            "someSpaceActivated:",
            NSWorkspaceActiveSpaceDidChangeNotification,
            None,
        )
