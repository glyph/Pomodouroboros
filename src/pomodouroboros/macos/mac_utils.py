"""
General-purpose PyObjC utilities that might belong in a different package.
"""

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import (
    Generic,
    Any,
    Callable,
    Concatenate,
    Iterator,
    Protocol,
    TypeVar,
    ParamSpec,
    overload,
)

import objc
from AppKit import (
    NSApplication,
    NSApplicationActivateIgnoringOtherApps,
    NSWorkspaceDidHideApplicationNotification,
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
SelfType = TypeVar("SelfType", contravariant=True)


class Descriptor(Protocol[ForGetting, ForSetting, SelfType]):
    def __get__(
        self, instance: SelfType, owner: type | None = None
    ) -> ForGetting:
        ...

    def __set__(self, instance: SelfType, value: ForSetting) -> None:
        ...


PyType = TypeVar("PyType")
ObjCType = TypeVar("ObjCType")
P = ParamSpec("P")
Attr = Descriptor[T, T, S]


def passthru(value: T) -> T:
    return value


@dataclass
class Forwarder(Generic[SelfType]):
    """
    A builder for descriptors that forward attributes from a (KVO, ObjC) facade
    object to an underlying original (regular Python) object.
    """

    original: str
    "The name of the attribute to forward things to."

    setterWrapper: Callable[
        [Callable[[SelfType, PyType], T]],
        Callable[[SelfType, PyType], T],
    ] = passthru

    @overload
    def forwarded(self, name: str) -> Descriptor[ObjCType, ObjCType, SelfType]:
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
    ) -> Descriptor[ObjCType, ObjCType, SelfType]:
        ...

    def forwarded(
        self,
        name: str,
        pyToC: Callable[[PyType], ObjCType] | None = None,
        cToPy: Callable[[ObjCType], PyType] | None = None,
    ) -> Descriptor[ObjCType, ObjCType, SelfType]:
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
    ) -> Descriptor[ObjCType, ObjCType, SelfType]:
        prop = objc.object_property()

        @prop.getter
        def getter(oself: SelfType) -> ObjCType:
            wrapped = getattr(oself, self.original)
            return pyToC(getattr(wrapped, name))

        getter.__name__ = f"get {name}"

        @getter.setter
        @self.setterWrapper
        def setter(oself: SelfType, value: ObjCType) -> None:
            wrapped = getattr(oself, self.original)
            setattr(wrapped, name, cToPy(value))

        setter.__name__ = f"set {name}"

        result: Descriptor[ObjCType, ObjCType, SelfType] = prop
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
        # NSLog(f"active {notification} {__file__}")
        whichApp = notification.userInfo()[NSWorkspaceApplicationKey]

        if whichApp == NSRunningApplication.currentApplication():
            if self.currentlyRegular:
                # NSLog("show editor window")
                self.mainWindow.setIsVisible_(True)
            else:
                # NSLog("reactivate workaround")
                self.currentlyRegular = True
                self.previouslyActiveApp.activateWithOptions_(
                    NSApplicationActivateIgnoringOtherApps
                )
                app = NSApplication.sharedApplication()
                app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
                from twisted.internet import reactor

                reactor.callLater(  # type:ignore[attr-defined]
                    0.1, lambda: app.activateIgnoringOtherApps_(True)
                )
        else:
            self.previouslyActiveApp = whichApp

    def someApplicationHidden_(self, notification: Any) -> None:
        """
        An app was hidden.
        """
        whichApp = notification.userInfo()[NSWorkspaceApplicationKey]
        if whichApp == NSRunningApplication.currentApplication():
            # 'hide others' (and similar functionality) should *not* hide the
            # progress window; that would obviate the whole point of having
            # this app live in the background in order to maintain a constant
            # presence in the user's visual field.  however if we're being told
            # to hide, don't ignore the user, hide the main window and retreat
            # into the background as if we were closed.
            self.mainWindow.close()
            app = NSApplication.sharedApplication()
            app.unhide_(self)

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
            "someApplicationHidden:",
            NSWorkspaceDidHideApplicationNotification,
            None,
        )

        wsnc.addObserver_selector_name_object_(
            self,
            "someSpaceActivated:",
            NSWorkspaceActiveSpaceDidChangeNotification,
            None,
        )
