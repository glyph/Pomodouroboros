from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from textwrap import dedent
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from AppKit import (
    NSAlert,
    NSAlertFirstButtonReturn,
    NSAlertSecondButtonReturn,
    NSAlertThirdButtonReturn,
    NSApp,
    NSApplication,
    NSApplicationActivationPolicyRegular,
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
    NSTableView,
    NSTextField,
    NSTextFieldCell,
    NSView,
    NSWindow,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorStationary,
)
from Foundation import NSObject
from objc import IBAction, IBOutlet
from twisted.internet.interfaces import IReactorTime
from twisted.internet.task import LoopingCall

from ..storage import TEST_MODE
from .old_mac_gui import main as oldMain
from .progress_hud import ProgressController
from .quickapp import mainpoint
from pomodouroboros.model.intention import Intention
from pomodouroboros.model.intervals import AnyInterval, StartPrompt
from pomodouroboros.model.nexus import Nexus
from pomodouroboros.model.storage import loadDefaultNexus


@dataclass
class MacUserInterface:
    """
    UI for the Mac.
    """

    pc: ProgressController
    clock: IReactorTime
    nexus: Nexus

    def intentionAdded(self, intention: Intention) -> None:
        ...

    def intentionAbandoned(self, intention: Intention) -> None:
        ...

    def intentionCompleted(self, intention: Intention) -> None:
        ...

    def intervalStart(self, interval: AnyInterval) -> None:
        print("interval started", interval)
        if isinstance(interval, StartPrompt):
            print(
                "you're about to lose",
                interval.pointsLost,
                "points, in",
                interval.endTime - interval.startTime,
                "seconds",
            )

    def intervalProgress(self, percentComplete: float) -> None:
        self.pc.animatePercentage(self.clock, percentComplete)

    def intervalEnd(self) -> None:
        print("interval ended")


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
    estimate: str

    if TYPE_CHECKING:

        @classmethod
        def alloc(self) -> IntentionRow:
            ...

    def initWithRowNumber_(self, rowNumber: int) -> IntentionRow:
        self.title = f"title {rowNumber}"
        self.textDescription = f"description {rowNumber}"
        self.estimate = f"estimate {rowNumber}"
        self.shouldHideEstimate = True
        creationDate = datetime.now(ZoneInfo("US/Pacific")) - timedelta(
            days=(10 - rowNumber)
        )
        modificationDate = creationDate + timedelta(days=2)
        self.creationText = f"Created at {creationDate.isoformat(timespec='minutes')}; Modified at {modificationDate.isoformat(timespec='minutes')}"
        self.canEditSummary = False
        return self

    @IBAction
    def estimateClicked_(self, target: object) -> None:
        self.shouldHideEstimate = not self.shouldHideEstimate

    def pomodoroListSummaryText(self) -> str:
        return dedent(
            """\
            • list
            • of
            • pomodoros
            • placeholder
        """
        )


class IntentionDataSource(NSObject):
    """
    NSTableViewDataSource for the list of intentions.
    """

    def numberOfRowsInTableView_(self, tableView: NSTableView) -> int:
        return 2

    def tableView_objectValueForTableColumn_row_(
        self, tableView, objectValueForTableColumn, row
    ) -> IntentionRow:
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
    NSApplication.sharedApplication().setActivationPolicy_(
        NSApplicationActivationPolicyRegular
    )

    pc = ProgressController()
    nexus = loadDefaultNexus(
        reactor.seconds(),
        userInterfaceFactory=lambda nexus: MacUserInterface(
            pc, reactor, nexus
        ),
    )
    # XXX test session
    nexus.addSession(reactor.seconds(), reactor.seconds() + 1000.0)

    def doAdvance() -> None:
        nexus.advanceToTime(reactor.seconds())

    LoopingCall(doAdvance).start(10.0)
    owner = PomFilesOwner.alloc().init().retain()
    NSNib.alloc().initWithNibNamed_bundle_(
        "MainMenu.nib", None
    ).instantiateWithOwner_topLevelObjects_(None, None)
    NSNib.alloc().initWithNibNamed_bundle_(
        "IntentionEditor.nib", None
    ).instantiateWithOwner_topLevelObjects_(owner, None)

    if TEST_MODE:
        # When I'm no longer bootstrapipng the application I'll want to *not*
        # unconditionally activate here, just have normal launch behavior.
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
