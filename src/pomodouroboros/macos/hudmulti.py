from typing import Self
from Foundation import NSMakePoint, NSNotification
from AppKit import (
    NSNib,
    NSObject,
    NSScreen,
    NSWindow,
    NSWorkspace,
    NSWorkspaceActiveSpaceDidChangeNotification,
)
from objc import IBOutlet, object_property, super

from .progress_hud import PieTimer


class HUDMultipleProgress(NSObject):
    """
    multiple progress
    """

    left: PieTimer
    left = IBOutlet()
    middle: PieTimer
    middle = IBOutlet()
    right: PieTimer
    right = IBOutlet()
    win: NSWindow
    win = IBOutlet()
    screen: NSScreen = object_property()

    def initWithScreen_(self, screen: NSScreen) -> Self:
        super().init()
        self.screen = screen
        return self

    def someSpaceActivated_(self, notification: NSNotification) -> None:
        print("IOAS", self.win.isOnActiveSpace())
        self.win.setIsVisible_(False)
        self.win.setIsVisible_(True)
        print("IOAS", self.win.isOnActiveSpace())

    def retain(self) -> Self:
        return super().retain()  # type:ignore[no-any-return]

    def repositionWindow(self) -> None:

        screenFrame = self.screen.frame()
        w = self.win.frame().size.width
        h = self.win.frame().size.height
        sw = screenFrame.size.width / 2
        sh = screenFrame.size.height * (5 / 6)
        winOrigin = NSMakePoint(
            screenFrame.origin.x + (sw - (w / 2)),
            screenFrame.origin.y + (sh - (h / 2)),
        )
        print(f"screenOrigin: {screenFrame.origin} winOrigin: {winOrigin}")
        self.win.setFrameOrigin_(winOrigin)


def debugMultiHud() -> None:
    print("multiHudDebug")
    nibInstance = NSNib.alloc().initWithNibNamed_bundle_(
        "ProgressHUD.nib", None
    )

    for screen in NSScreen.screens():
        owner = HUDMultipleProgress.alloc().initWithScreen_(screen).retain()

        loaded, tlos = nibInstance.instantiateWithOwner_topLevelObjects_(
            owner, None
        )

        owner.repositionWindow()

        owner.left.setPercentage_(0.1)
        owner.middle.setPercentage_(0.2)
        owner.right.setPercentage_(0.3)

        wsnc = NSWorkspace.sharedWorkspace().notificationCenter()
        wsnc.addObserver_selector_name_object_(
            owner,
            "someSpaceActivated:",
            NSWorkspaceActiveSpaceDidChangeNotification,
            None,
        )

        print("OK")
