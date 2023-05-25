from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import wraps
from textwrap import dedent
from typing import Any, Callable, Generic, TYPE_CHECKING, TypeVar

import objc
from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyRegular,
    NSColor,
    NSMakeRect,
    NSMakeSize,
    NSMenu,
    NSMenuItem,
    NSNib,
    NSNotification,
    NSRect,
    NSSize,
    NSTableView,
    NSTextField,
    NSTextFieldCell,
    NSTextView,
    NSWindow,
)
from Foundation import NSIndexSet, NSObject
from objc import IBAction, IBOutlet, super
from quickmacapp import Status, mainpoint
from twisted.internet.interfaces import IReactorTime
from twisted.internet.task import LoopingCall

from ..model.intention import Intention
from ..model.intervals import AnyInterval, StartPrompt
from ..model.nexus import Nexus
from ..model.storage import loadDefaultNexus
from ..storage import TEST_MODE
from .mac_utils import showFailures, Forwarder
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


class TabOrderFriendlyTextViewDelegate(NSObject):
    """
    Act as a NSTextViewDelegate to allow for tab/backtab (i.e. shift-tab) to
    cycle through focus elements, since we're not going to be putting literal
    tabs into descriptions.
    """

    def textView_doCommandBySelector_(
        self, aTextView: NSTextView, aSelector: str
    ) -> bool:
        match aSelector:
            case "insertTab:":
                aTextView.window().selectNextKeyView_(None)
                return True
            case "insertBacktab:":
                aTextView.window().selectPreviousKeyView_(None)
                return True
            case _:
                return False


class IntentionRow(NSObject):
    """
    A row in the intentions table; ObjC wrapper for L{IntentionRow}.
    """

    # pragma mark Initialization
    if TYPE_CHECKING:

        @classmethod
        def alloc(cls) -> IntentionRow:
            ...

    def initWithIntention_andNexus_(
        self, intention: Intention, nexus: Nexus
    ) -> IntentionRow:
        super().init()
        self.intention = intention
        self.shouldHideEstimate = True
        self.canEditSummary = False
        return self

    # pragma mark Attributes

    intention: Intention = objc.object_property()
    shouldHideEstimate = objc.object_property()
    canEditSummary = objc.object_property()

    hasColor = objc.object_property()  # this one probably needs to be
    # forwarded once we get color support
    # into the intention model

    forwarded = Forwarder("intention").forwarded

    title: str = forwarded("title")
    textDescription: str = forwarded("description")

    _estimate = objc.object_property()

    @_estimate.getter
    def estimate(self) -> str:
        estimates = self.intention.estimates
        return str(estimates[-1] if estimates else "")

    _creationText = objc.object_property()

    @_creationText.getter
    def creationText(self) -> str:
        creationDate = datetime.fromtimestamp(self.intention.created)
        return f"{creationDate.isoformat(timespec='minutes', sep=' ')}"

    _modificationText = objc.object_property()

    @_modificationText.getter
    def modificationText(self):
        """ """
        modificationDate = datetime.fromtimestamp(self.intention.modified)
        return f"{modificationDate.isoformat(timespec='minutes', sep=' ')}"


from weakref import ref

T = TypeVar("T")
U = TypeVar("U")
S = TypeVar("S")


@dataclass
class IDHasher(Generic[T]):
    """
    Hash and compare by the identity of another object.
    """

    value: ref[T]
    id: int

    def __hash__(self) -> int:
        """
        Return the C{id()} of the object when it was live at the creation of
        this hasher.
        """
        return self.id

    def __eq__(self, other: object) -> bool:
        """
        Is this equal to another object?  Note that this compares equal only to
        another L{IDHasher}, not the underlying value object.
        """
        if not isinstance(other, IDHasher):
            return NotImplemented
        imLive = self.value.__callback__ is not None
        theyreLive = other.value.__callback__ is not None
        return (self.id == other.id) and (imLive == theyreLive)

    @classmethod
    def forDict(cls, aDict: dict[IDHasher[T], U], value: T) -> IDHasher[T]:
        """
        Create an IDHasher
        """

        def finalize(r: ref[T]) -> None:
            del aDict[self]

        self = IDHasher(ref(value, finalize), id(value))
        return self


@dataclass
class ModelConverter(Generic[T, U]):
    """
    Convert C{T} objects (abstract model; Python objects) to C{U} objects (UI
    model; Objective C objects).
    """

    translator: Callable[[T], U]
    _cache: dict[IDHasher[T], U] = field(default_factory=dict)

    def __getitem__(self, key: T) -> U:
        """
        Look up or create the relevant item.
        """
        hasher = IDHasher.forDict(self._cache, key)
        value = self._cache.get(hasher)
        if value is not None:
            return value
        value = self.translator(key)
        self._cache[hasher] = value
        return value


"""
data source template:

class _(NSObject):
    def awakeWithNexus_(self, newNexus: Nexus) -> None:
        ...
    # pragma mark NSTableViewDataSource

    def numberOfRowsInTableView_(self, tableView: NSTableView) -> int:
        ...

    def tableView_objectValueForTableColumn_row_(
        self,
        tableView: NSTableView,
        objectValueForTableColumn: NSObject,
        row: int,
    ) -> str:
        ...

"""


class IntentionDataSource(NSObject):
    """
    NSTableViewDataSource for the list of intentions.
    """

    # pragma mark Attributes

    intentionRowMap: ModelConverter[Intention, IntentionRow]
    nexus: Nexus | None = None

    selectedIntention: IntentionRow | None = objc.object_property()
    "everything in the detail view is bound to this"

    hasNoSelection: bool = objc.object_property()
    "detail view's 'hidden' is bound to this"

    # pragma mark Initialization and awakening

    def init(self) -> IntentionDataSource:
        """
        Construct an L{IntentionDataSource}.  This is constructed in the nib.
        """
        self.hasNoSelection = True
        self.selectedIntention = None
        return self

    def awakeWithNexus_(self, newNexus: Nexus) -> None:
        """
        Complete initialization after awakeFromNib by associating everything
        with a 'nexus'.
        """
        self.nexus = newNexus

        @ModelConverter
        def translator(intention: Intention) -> IntentionRow:
            assert self.nexus is not None, "what"
            return IntentionRow.alloc().initWithIntention_andNexus_(
                intention, self.nexus
            )

        self.intentionRowMap = translator

    # pragma mark My own methods

    def rowObjectAt_(self, index: int) -> IntentionRow:
        """
        Look up a row object at the given index.
        """
        assert self.nexus is not None
        return self.intentionRowMap[self.nexus.intentions[index]]

    # pragma mark NSTableViewDelegate

    def tableViewSelectionDidChange_(self, notification: NSObject) -> None:
        """
        The selection changed.
        """
        tableView = notification.object()
        idx = tableView.selectedRow()

        if idx == -1:
            self.selectedIntention = None
            self.hasNoSelection = True
            return

        self.selectedIntention = self.rowObjectAt_(idx)
        self.hasNoSelection = False

    # pragma mark NSTableViewDataSource

    def numberOfRowsInTableView_(self, tableView: NSTableView) -> int:
        """
        Implement NSTableViewDataSource numberOfRowsInTableView:
        """
        if self.nexus is None:
            return 0
        result = len(self.nexus.intentions)
        return result

    def tableView_objectValueForTableColumn_row_(
        self,
        tableView: NSTableView,
        objectValueForTableColumn: NSObject,
        row: int,
    ) -> str:
        """
        Implement NSTableViewDataSource tableView:objectValueForTableColumn:row:
        """
        with showFailures():
            rowValue = self.rowObjectAt_(row)
            return rowValue


class IntentionPomodorosDataSource(NSObject):
    # pragma mark NSTableViewDataSource

    def numberOfRowsInTableView_(self, tableView: NSTableView) -> int:
        return 7

    def tableView_objectValueForTableColumn_row_(
        self,
        tableView: NSTableView,
        objectValueForTableColumn: NSObject,
        row: int,
    ) -> dict:
        # oip: OneIntentionPom = OneIntentionPom.alloc().init()
        # return oip
        return {
            "date": "synthetic date value",
            "startTime": "synthetic start time",
            "endTime": "synthetic end time",
            "evaluation": "here you go",
            "inSession": "\N{CHECK MARK}",
        }

class OneIntentionPom(NSObject):
    date = objc.object_property()

    @date.getter                # type:ignore
    def date(self) -> str:
        return "date property text"

    def init(self) -> OneIntentionPom:
        super().init()
        return self


class StreakDataSource(NSObject):
    """
    NSTableViewDataSource for the list of streaks.
    """


class PomFilesOwner(NSObject):
    nexus: Nexus

    # Note: Xcode can't see IBOutlet declarations on the same line as their
    # type hint.
    sessionDataSource = IBOutlet()  # type: SessionDataSource
    intentionDataSource = IBOutlet()  # type: IntentionDataSource
    streakDataSource = IBOutlet()  # type: StreakDataSource

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
        self.intentionsTable.selectRowIndexes_byExtendingSelection_(
            NSIndexSet.indexSetWithIndex_(len(self.nexus.intentions) - 1),
            False,
        )

    @IBAction
    def pokeIntentionDescription_(self, sender: NSObject) -> None:
        irow = (
            # self.intentionDataSource.tableView_objectValueForTableColumn_row_(
            #     self.intentionsTable, None, 0
            # )
            self.intentionDataSource.rowObjectAt_(0)
        )
        irow.textDescription = "new description"
        irow.title = "new title"

    def awakeFromNib(self) -> None:
        """
        Let's get the GUI started.
        """
        # TODO: update intention data source with initial data from nexus
        self.intentionDataSource.awakeWithNexus_(self.nexus)
        self.debugPalette.setOpaque_(False)
        self.debugPalette.setBackgroundColor_(NSColor.clearColor())
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
    theNexus.userInterface
    # hmm. UI is lazily constructed which is not great, violates the mac's
    # assumptions about launching, makes it seem sluggish, so let's force it to
    # be eager here.
    # XXX test session
    theNexus.addSession(reactor.seconds() + 1.0, reactor.seconds() + 1000.0)

    def doAdvance() -> None:
        theNexus.advanceToTime(reactor.seconds())

    LoopingCall(doAdvance).start(3.0, now=True)

    if TEST_MODE:
        # When I'm no longer bootstrapping the application I'll want to *not*
        # unconditionally activate here, just have normal launch behavior.
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
