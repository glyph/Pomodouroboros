from AppKit import (
    NSNib,
    NSObject,
    NSWindow,
    NSWorkspace,
    NSWorkspaceActiveSpaceDidChangeNotification,
)
from objc import IBOutlet

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

    def someSpaceActivated_(self, theSpace) -> None:
        print("IOAS", self.win.isOnActiveSpace())
        self.win.setIsVisible_(False)
        self.win.setIsVisible_(True)
        print("IOAS", self.win.isOnActiveSpace())


def debugMultiHud() -> None:
    print("multiHudDebug")
    nibInstance = NSNib.alloc().initWithNibNamed_bundle_(
        "ProgressHUD.nib", None
    )
    owner = HUDMultipleProgress.alloc().init().retain()
    loaded, tlos = nibInstance.instantiateWithOwner_topLevelObjects_(
        owner, None
    )

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
