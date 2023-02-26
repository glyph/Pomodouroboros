from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from textwrap import dedent
from typing import Sequence, TYPE_CHECKING, Iterator
from zoneinfo import ZoneInfo
from contextlib import contextmanager

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
    NSMakeRect,
    NSMakeSize,
    NSMenu,
    NSMenuItem,
    NSNib,
    NSNotification,
    NSNotificationCenter,
    NSRect,
    NSRectFill,
    NSRectFillListWithColorsUsingOperation,
    NSResponder,
    NSScreen,
    NSSize,
    NSTableView,
    NSTextField,
    NSTextFieldCell,
    NSView,
    NSViewHeightSizable,
    NSViewNotSizable,
    NSViewWidthSizable,
    NSWindow,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorStationary,
)
from Foundation import NSObject
from objc import IBAction, IBOutlet

from twisted.internet.interfaces import IReactorTime
from twisted.internet.task import LoopingCall

from quickmacapp import Status, mainpoint

from ..model.intention import Intention
from ..model.intervals import AnyInterval, StartPrompt
from ..model.nexus import Nexus
from ..model.storage import loadDefaultNexus
from ..storage import TEST_MODE
from .old_mac_gui import main as oldMain
from .progress_hud import ProgressController


@dataclass
class MacUserInterface:
    """
    UI for the Mac.
    """

    pc: ProgressController
    clock: IReactorTime
    nexus: Nexus
    explanatoryLabel: HeightSizableTextField
    currentInterval: AnyInterval | None = None

    def startPromptUpdate(self, startPrompt: StartPrompt) -> None:
        """
        You're in a start prompt, update the description to explain to the user
        what should happen next.
        """
        self.setExplanation(
            f"You're about to lose {startPrompt.pointsLost:g} points, in about "
            f"{startPrompt.endTime - self.clock.seconds():.0f} seconds, "
            "if you don’t start a pomodoro."
        )

    def intentionAdded(self, intention: Intention) -> None:
        ...

    def intentionAbandoned(self, intention: Intention) -> None:
        ...

    def intentionCompleted(self, intention: Intention) -> None:
        ...

    def intervalStart(self, interval: AnyInterval) -> None:
        self.currentInterval = interval
        match interval:
            case StartPrompt():
                self.startPromptUpdate(interval)

    def intervalProgress(self, percentComplete: float) -> None:
        match self.currentInterval:
            case StartPrompt():
                self.startPromptUpdate(self.currentInterval)
        self.pc.animatePercentage(self.clock, percentComplete)

    def intervalEnd(self) -> None:
        print("interval ended")

    def setExplanation(self, explanatoryText) -> None:
        """
        Change the explanatory text of the menu label to explain what is going
        on so the user can see what the deal is.
        """
        self.explanatoryLabel.setStringValue_(explanatoryText)
        for repeat in range(3):
            self.explanatoryLabel.setFrameSize_(
                self.explanatoryLabel.intrinsicContentSize()
            )

    @classmethod
    def build(cls, nexus: Nexus, clock: IReactorTime) -> MacUserInterface:
        """
        Create a MacUserInterface and all its constituent widgets.
        """
        owner = PomFilesOwner.alloc().initWithNexus_(nexus).retain()
        NSNib.alloc().initWithNibNamed_bundle_(
            "MainMenu.nib", None
        ).instantiateWithOwner_topLevelObjects_(None, None)
        NSNib.alloc().initWithNibNamed_bundle_(
            "IntentionEditor.nib", None
        ).instantiateWithOwner_topLevelObjects_(owner, None)

        def openWindow() -> None:
            owner.intentionsWindow.makeKeyAndOrderFront_(owner)
            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

        status = Status("🍅🔰")
        status.menu([("Open Window", openWindow)])
        return cls(
            ProgressController(),
            clock,
            nexus,
            makeMenuLabel(status.item.menu()),
        )


def makeMenuLabel(menu: NSMenu, index: int = 0) -> HeightSizableTextField:
    """
    Make a label in the given menu
    """
    viewItem = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "ignored", "doIt:", "k"
    )
    menu.insertItem_atIndex_(viewItem, 0)
    explanatoryLabel: HeightSizableTextField = (
        HeightSizableTextField.wrappingLabelWithString_("Starting Up…")
    )
    viewItem.setView_(explanatoryLabel)
    explanatoryLabel.setMaximumNumberOfLines_(100)
    explanatoryLabel.setSelectable_(False)
    explanatoryLabel.setTextColor_(NSColor.secondaryLabelColor())
    return explanatoryLabel


class SessionDataSource(NSObject):
    """
    NSTableViewDataSource for the list of active sessions.
    """


class IntentionRow(NSObject):
    """
    A row in the intentions table.
    """

    if TYPE_CHECKING:

        @classmethod
        def alloc(self) -> IntentionRow:
            ...

    def title(self) -> str:
        return self._intention.title

    def setTitle_(self, newTitle: str) -> None:
        self._intention.title = newTitle

    def textDescription(self) -> str:
        return self._intention.description

    def setTextDescription_(self, newTextDescription: str) -> None:
        self._intention.description = newTextDescription

    def estimate(self) -> str:
        estimates = self._intention.estimates
        return str(estimates[-1] if estimates else "")

    def creationText(self) -> str:
        creationDate = datetime.fromtimestamp(self._intention.created)
        modificationDate = creationDate + timedelta(days=2)
        return (
            f"Created at {creationDate.isoformat(timespec='minutes')}; "
            f"Modified at {modificationDate.isoformat(timespec='minutes')}"
        )

    def initWithIntention_andNexus_(self, intention: Intention, nexus: Nexus) -> IntentionRow:
        self._intention = intention
        self.shouldHideEstimate = True
        self.canEditSummary = False
        return self

    @IBAction
    def setClicked_(self, target: object) -> None:
        """
        The 'set' button was clicked. Time to set this intention!
        """
        print("set intention clicked for", self._intention)

    @IBAction
    def abandonClicked_(self, target: object) -> None:
        """
        The 'abandon' button was clicked.  This intention should be abandoned
        (after a confirmation dialog).
        """
        print("abandon intention clicked for", self._intention)

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

from twisted.python.failure import Failure
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

class IntentionDataSource(NSObject):
    """
    NSTableViewDataSource for the list of intentions.
    """

    intentionsList: Sequence[Intention] = ()
    nexus: Nexus | None = None

    def numberOfRowsInTableView_(self, tableView: NSTableView) -> int:
        if self.nexus is None:
            return 0
        result = len(self.intentionsList)
        return result

    def tableView_objectValueForTableColumn_row_(
        self, tableView: NSTableView, objectValueForTableColumn: object, row: int,
    ) -> IntentionRow:
        with showFailures():
            r = self.intentionsList[row]
            assert self.nexus is not None
            ira = IntentionRow.alloc().initWithIntention_andNexus_(r, self.nexus)
            return ira


class StreakDataSource(NSObject):
    """
    NSTableViewDataSource for the list of streaks.
    """


class PomFilesOwner(NSObject):
    nexus: Nexus

    # Note: Xcode can't see IBOutlet declarations on the same line as their
    # type hint.
    sessionDataSource: SessionDataSource
    sessionDataSource = IBOutlet()

    intentionDataSource: IntentionDataSource
    intentionDataSource = IBOutlet()

    streakDataSource: StreakDataSource
    streakDataSource = IBOutlet()

    intentionsWindow: NSWindow
    intentionsWindow = IBOutlet()

    intentionsTable: NSTableView
    intentionsTable = IBOutlet()

    debugPalette: NSWindow
    debugPalette = IBOutlet()

    if TYPE_CHECKING:
        @classmethod
        def alloc(self) -> PomFilesOwner:
            ...

    def initWithNexus_(self, nexus: Nexus) -> PomFilesOwner:
        """
        Initialize a pomfilesowner with a nexus
        """
        self.nexus = nexus
        return self

    @IBAction
    def newIntentionClicked_(self, sender: NSObject) -> None:
        """
        The 'new intention' button was clicked.
        """
        newIntention = self.nexus.addIntention()
        self.intentionsTable.reloadData()

    @IBAction
    def pokeIntentionDescription_(self, sender: NSObject) -> None:
        self.intentionDataSource.intentionsList[0].description = 'new description'
        self.intentionsTable.reloadData()

    def awakeFromNib(self) -> None:
        """
        Let's get the GUI started.
        """
        # TODO: update intention data source with initial data from nexus
        self.intentionDataSource.intentionsList = self.nexus.intentions
        self.intentionDataSource.nexus = self.nexus
        self.debugPalette.setIsVisible_(True)


leftPadding = 15.0


class HeightSizableTextField(NSTextField):
    """
    Thanks https://stackoverflow.com/a/10463761/13564
    """

    def intrinsicContentSize(self) -> NSSize:
        """
        Calculate the intrinsic content size based on height.
        """
        if not self.cell().wraps():
            return super().intrinsicContentSize()

        frame = self.frame()
        width = 350.0  # frame.size.width
        origHeight = frame.size.height
        frame.size.height = 99999.0
        cellHeight = self.cell().cellSizeForBounds_(frame).height
        height = cellHeight + (leftPadding * 2)
        return NSMakeSize(width, height)

    def textDidChange_(self, notification: NSNotification) -> None:
        """
        The text changed, recalculate please
        """
        super().textDidChange_(notification)
        self.invalidateIntrinsicContentSize()

    @classmethod
    def cellClass(cls) -> type[PaddedTextFieldCell]:
        """
        Customize the cell class so that it includes some padding

        @note: C{cellClass} is nominally deprecated (as is C{cell}), but there
            doesn't seem to be any reasonable way to do this sort of basic
            customization that I{isn't} deprecated.  It seems like Apple mainly
            wants to deprecate the use of this customization mechanism in
            NSTableView usage?
        """
        return PaddedTextFieldCell


class PaddedTextFieldCell(NSTextFieldCell):
    """
    NSTextFieldCell subclass that adds some padding so it looks a bit more
    legible in the context of a popup menu label, with horizontal and vertical
    padding so that it is offset from the menu items.
    """

    def drawingRectForBounds_(self, rect: NSRect) -> NSRect:
        """
        Compute an inset drawing rect for the text.
        """
        rectInset = NSMakeRect(
            rect.origin.x + leftPadding,
            rect.origin.y + leftPadding,
            rect.size.width - (leftPadding * 2),
            rect.size.height - (leftPadding * 2),
        )
        return super().drawingRectForBounds_(rectInset)


@mainpoint()
def main(reactor: IReactorTime) -> None:
    """
    Run oldMain by default so I can keep using the app while I'm working on a
    radical refactor of the object model in newMain.
    """
    if TEST_MODE:
        return newMain(reactor)
    else:
        return oldMain(reactor)


def newMain(reactor: IReactorTime) -> None:
    """
    New pomodoro.model.nexus-based implementation of the UI.
    """

    NSApplication.sharedApplication().setActivationPolicy_(
        NSApplicationActivationPolicyRegular
    )

    theNexus = loadDefaultNexus(
        reactor.seconds(),
        userInterfaceFactory=lambda nexus: MacUserInterface.build(
            nexus, reactor
        ),
    )
    # XXX test session
    theNexus.addSession(reactor.seconds(), reactor.seconds() + 1000.0)

    def doAdvance() -> None:
        theNexus.advanceToTime(reactor.seconds())

    LoopingCall(doAdvance).start(10.0)

    if TEST_MODE:
        # When I'm no longer bootstrapping the application I'll want to *not*
        # unconditionally activate here, just have normal launch behavior.
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
