"""
General-purpose PyObjC utilities that might belong in a different package.
"""

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import (
    Any,
    Callable,
    Iterator,
    Protocol,
    TypeVar,
    overload,
)

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
    NSLog,
    NSObject,
)
from quickmacapp import Actionable
from twisted.python.failure import Failure


T = TypeVar("T")
S = TypeVar("S")

ForGetting = TypeVar("ForGetting", covariant=True)
ForSetting = TypeVar("ForSetting", contravariant=True)


class Descriptor(Protocol[ForGetting, ForSetting]):
    def __get__(
        self, instance: object, owner: type | None = None
    ) -> ForGetting:
        ...

    def __set__(self, instance: object, value: ForSetting) -> None:
        ...


PyType = TypeVar("PyType")
ObjCType = TypeVar("ObjCType")

Attr = Descriptor[T, T]


def passthru(value: T) -> T:
    return value


@dataclass
class Forwarder:
    """
    A builder for descriptors that forward attributes from a (KVO, ObjC) facade
    object to an underlying original (regular Python) object.
    """

    original: str
    "The name of the attribute to forward things to."

    @overload
    def forwarded(self, name: str) -> Descriptor[ObjCType, ObjCType]:
        """
        Create an attribute that will forward to C{name}.

        @param name: The name of the attribute on C{instance.<original>} to
            forward this attribute to.

        @returns: A descriptor that reads and writes the Objective C type.
        """

    @overload
    def forwarded(
        self,
        name: str,
        pyToC: Callable[[PyType], ObjCType],
        cToPy: Callable[[ObjCType], PyType],
    ) -> Descriptor[ObjCType, ObjCType]:
        ...

    def forwarded(
        self,
        name: str,
        pyToC: Callable[[PyType], ObjCType] | None = None,
        cToPy: Callable[[ObjCType], PyType] | None = None,
    ) -> Descriptor[ObjCType, ObjCType]:
        realPyToC: Callable[[PyType], ObjCType] = (
            pyToC if pyToC is not None else passthru  # type:ignore[assignment]
        )
        realCToPy: Callable[[ObjCType], PyType] = (
            cToPy if cToPy is not None else passthru  # type:ignore[assignment]
        )
        return self._forwardedImpl(name, realPyToC, realCToPy)

    def _forwardedImpl(
        self,
        name: str,
        pyToC: Callable[[PyType], ObjCType],
        cToPy: Callable[[ObjCType], PyType],
    ) -> Descriptor[ObjCType, ObjCType]:
        prop = objc.object_property()

        @prop.getter
        def getter(oself: object) -> ObjCType:
            wrapped = getattr(oself, self.original)
            return pyToC(getattr(wrapped, name))

        @getter.setter
        def setter(oself: object, value: ObjCType) -> None:
            wrapped = getattr(oself, self.original)
            setattr(wrapped, name, cToPy(value))

        result: Descriptor[ObjCType, ObjCType] = prop
        return result


@dataclass
class _ObserverRemover:

    center: NSNotificationCenter | None
    name: str
    observer: NSObject
    sender: NSObject | None

    def removeObserver(self) -> None:
        center = self.center
        if center is None:
            return
        self.center = None
        # lifecycle management: paired with observer.retain() in callOnNotification
        self.observer.release()
        if self.sender is not None:
            # Unused, but lifecycle management would demand sender be retained
            # by any observer-adding code as well.
            self.sender.release()
        center.removeObserver_name_object_(
            self.observer,
            self.name,
        )


class ObserverRemover(Protocol):
    """
    Handle to an observer that is added to a given L{NSNotificationCenter} (by
    L{callOnNotification}).
    """

    def removeObserver(self) -> None:
        """
        Remove the observer added by L{callOnNotification}.
        """


def callOnNotification(
    nsNotificationName: str, f: Callable[[], None]
) -> ObserverRemover:
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
    return _ObserverRemover(
        defaultCenter,
        nsNotificationName,
        observer,
        sender,
    )


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
        if notification.object() == self.mainWindow:
            self.currentlyRegular = False
            NSApplication.sharedApplication().setActivationPolicy_(
                NSApplicationActivationPolicyAccessory
            )

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
