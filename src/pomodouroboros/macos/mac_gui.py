from __future__ import annotations
from dataclasses import dataclass
from typing import TYPE_CHECKING

from twisted.internet.interfaces import IReactorTime

from ..storage import TEST_MODE
from .old_mac_gui import main as oldMain
from .quickapp import mainpoint
from pomodouroboros.model.intention import Intention
from pomodouroboros.model.intervals import AnyInterval
from pomodouroboros.model.nexus import Nexus
from pomodouroboros.model.storage import loadDefaultNexus

from Foundation import NSObject
from objc import IBAction, IBOutlet

from AppKit import (
    NSApplication,
    NSAlert,
    NSAlertFirstButtonReturn,
    NSAlertSecondButtonReturn,
    NSAlertThirdButtonReturn,
    NSApp,
    NSApplicationDidChangeScreenParametersNotification,
    NSBackingStoreBuffered,
    NSBezierPath,
    NSBorderlessWindowMask,
    NSCell,
    NSColor,
    NSCompositingOperationCopy,
    NSEvent,
    NSFloatingWindowLevel,
    NSFocusRingTypeNone,
    NSMenu,
    NSMenuItem,
    NSNib,
    NSNotificationCenter,
    NSRectFill,
    NSRectFillListWithColorsUsingOperation,
    NSResponder,
    NSScreen,
    NSTextField,
    NSTextFieldCell,
    NSView,
    NSWindow,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorStationary,
    NSApplicationActivationPolicyRegular,
    NSTableView,
)


@dataclass
class MacUserInterface:
    """
    UI for the Mac.
    """

    nexus: Nexus

    def intentionAdded(self, intention: Intention) -> None:
        ...

    def intentionAbandoned(self, intention: Intention) -> None:
        ...

    def intentionCompleted(self, intention: Intention) -> None:
        ...

    def intervalStart(self, interval: AnyInterval) -> None:
        ...

    def intervalProgress(self, percentComplete: float) -> None:
        ...

    def intervalEnd(self) -> None:
        ...


class SessionDataSource(NSObject):
    """
    NSTableViewDataSource for the list of active sessions.
    """


class IntentionRow(NSObject):
    """
    A row in the intentions table.
    """
    title: str
    description: str

    if TYPE_CHECKING:
        @classmethod
        def alloc(self) -> IntentionRow:
            ...

    def initWithRowNumber_(self, rowNumber: int) -> IntentionRow:
        self.title = f"title {rowNumber}"
        self.textDescription = f"description {rowNumber}"
        return self

class IntentionDataSource(NSObject):
    """
    NSTableViewDataSource for the list of intentions.
    """
    def numberOfRowsInTableView_(self, tableView: NSTableView) -> int:
        return 2

    def tableView_objectValueForTableColumn_row_(self, tableView, objectValueForTableColumn, row) -> IntentionRow:
        return IntentionRow.alloc().initWithRowNumber_(row)


class StreakDataSource(NSObject):
    """
    NSTableViewDataSource for the list of streaks.
    """


class PomFilesOwner(NSObject):
    sessionDataSource: SessionDataSource = IBOutlet()
    intentionDataSource: IntentionDataSource = IBOutlet()
    streakDataSource: StreakDataSource = IBOutlet()

    def awakeFromNib(self) -> None:
        """
        Let's get the GUI started.
        """
        print(
            "objects:",
            self.sessionDataSource,
            self.intentionDataSource,
            self.streakDataSource,
        )


@mainpoint()
def main(reactor: IReactorTime) -> None:
    if not TEST_MODE:
        return oldMain(reactor)
    NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyRegular)

    nexus = loadDefaultNexus(
        reactor.seconds(), userInterfaceFactory=MacUserInterface
    )
    owner = PomFilesOwner.alloc().init().retain()
    NSNib.alloc().initWithNibNamed_bundle_(
        "MainMenu.nib", None
    ).instantiateWithOwner_topLevelObjects_(None, None)
    NSNib.alloc().initWithNibNamed_bundle_(
        "IntentionEditor.nib", None
    ).instantiateWithOwner_topLevelObjects_(owner, None)
    if TEST_MODE:
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
