from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from functools import wraps
from typing import (
    ClassVar,
    Callable,
    Generic,
    Sequence,
    TYPE_CHECKING,
    TypeVar,
    ParamSpec,
    Concatenate,
    Protocol,
)

import objc
from AppKit import (
    NSApplication,
    NSColor,
    NSNib,
    NSTableView,
    NSWindow,
)
from Foundation import NSIndexSet, NSObject

from objc import IBAction, IBOutlet, super
from pomodouroboros.macos.mac_utils import Attr, Descriptor, SometimesBackground
from quickmacapp import Status, mainpoint
from twisted.internet.interfaces import IReactorTime
from twisted.internet.task import LoopingCall

from ..hasher import IDHasher
from ..model.intention import Intention
from ..model.intervals import AnyInterval, Pomodoro, StartPrompt
from ..model.nexus import Nexus
from ..model.storage import loadDefaultNexus, saveDefaultNexus
from ..storage import TEST_MODE
from .mac_utils import Forwarder, showFailures
from .mac_dates import LOCAL_TZ
from .old_mac_gui import main as oldMain
from .progress_hud import ProgressController
from .text_fields import makeMenuLabel, HeightSizableTextField

# Imported only for side-effect of becoming known to ObjC runtime
from .tab_order import TabOrderFriendlyTextViewDelegate as _


class HasNexus(Protocol):
    nexus: Nexus


C = TypeVar("C", bound=Callable[..., object])
P = ParamSpec("P")
HN = TypeVar("HN", bound=HasNexus)


def interactionRoot(
    c: Callable[Concatenate[HN, P], T]
) -> Callable[Concatenate[HN, P], T]:
    @wraps(c)
    def g(self: HN, *args: P.args, **kwargs: P.kwargs) -> T:
        # idea: maybe maintain a trail of N backups here, for easy undo/revert
        # of certain edit actions?
        result = c(self, *args, **kwargs)
        saveDefaultNexus(self.nexus)
        return result

    return g


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
            # TODO: this should be in the model somewhere, not ad-hoc in the
            # middle of one frontend
            f"Set an intention within {startPrompt.endTime - self.clock.seconds():.0f}"
            f" seconds, or lose the chance to get {startPrompt.pointsLost:g} points!"
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
        self.pc.setReticleText(explanatoryText)
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
            "IntentionEditor.nib", None
        ).instantiateWithOwner_topLevelObjects_(owner, None)
        pc = ProgressController()
        SometimesBackground(
            owner.intentionsWindow, pc.redisplay
        ).startObserving()

        def openWindow() -> None:
            owner.intentionsWindow.makeKeyAndOrderFront_(owner)
            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

        status = Status("🍅🔰")
        status.menu([("Open Window", openWindow)])
        return cls(
            pc,
            clock,
            nexus,
            makeMenuLabel(status.item.menu()),
        )


class SessionDataSource(NSObject):
    """
    NSTableViewDataSource for the list of active sessions.
    """


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
        self.nexus = nexus
        self.intention = intention
        self.shouldHideEstimate = True
        self.canEditSummary = False
        return self

    # pragma mark Attributes

    _forwarded = Forwarder(
        "intention", setterWrapper=interactionRoot
    ).forwarded

    title: Attr[str, IntentionRow] = _forwarded("title")
    textDescription: Attr[str, IntentionRow] = _forwarded("description")

    nexus: Nexus = objc.object_property()
    intention: Intention = objc.object_property()
    shouldHideEstimate = objc.object_property()
    canEditSummary = objc.object_property()
    hasColor = objc.object_property()
    colorValue = objc.object_property()
    estimate = objc.object_property()
    creationText = objc.object_property()
    modificationText = objc.object_property()

    del _forwarded

    # pragma mark Accessors & Mutators

    @colorValue.getter
    def _getColorValue(self) -> NSColor:
        return self._colorValue

    @colorValue.setter
    @interactionRoot
    def _setColorValue(self, colorValue: NSColor) -> None:
        print("setting", colorValue)
        self._colorValue = colorValue
        print("set", colorValue)

    @estimate.getter
    def _getEstimate(self) -> str:
        estimates = self.intention.estimates
        return str(estimates[-1] if estimates else "")

    @creationText.getter
    def _getCreationText(self) -> str:
        creationDate = datetime.fromtimestamp(self.intention.created)
        return f"{creationDate.isoformat(timespec='minutes', sep=' ')}"

    @modificationText.getter
    def _getModificationText(self):
        modificationDate = datetime.fromtimestamp(self.intention.modified)
        return f"{modificationDate.isoformat(timespec='minutes', sep=' ')}"


T = TypeVar("T")
U = TypeVar("U")
S = TypeVar("S")


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

    intentionRowMap: ModelConverter[Intention, IntentionRow] = objc.object_property()
    nexus: Nexus | None = objc.object_property()

    selectedIntention: IntentionRow | None = objc.object_property()
    "everything in the detail view is bound to this"

    hasNoSelection: bool = objc.object_property()
    "detail view's 'hidden' is bound to this"

    pomsData: IntentionPomodorosDataSource
    pomsData = IBOutlet()

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

    @interactionRoot
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
        self.pomsData.backingData = self.selectedIntention.intention.pomodoros
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
    backingData: Sequence[Pomodoro] = []

    def numberOfRowsInTableView_(self, tableView: NSTableView) -> int:
        return len(self.backingData)

    def tableView_objectValueForTableColumn_row_(
        self,
        tableView: NSTableView,
        objectValueForTableColumn: NSObject,
        row: int,
    ) -> dict:
        # oip: OneIntentionPom = OneIntentionPom.alloc().init()
        # return oip
        realPom = self.backingData[row]
        dt = datetime.fromtimestamp(realPom.startTime, LOCAL_TZ)
        et = datetime.fromtimestamp(realPom.endTime, LOCAL_TZ)
        e = realPom.evaluation
        return {
            "date": str(dt.date()),
            "startTime": str(dt.time()),
            "endTime": str(et.time()),
            "evaluation": "" if e is None else str(e.result),
            # TODO: should be a clickable link to the session that this was in,
            # but first we need that feature from the model.
            "inSession": "???",
        }


class StreakDataSource(NSObject):
    """
    NSTableViewDataSource for the list of streaks.
    """

    # backingData: Sequence[Streak]

    def awakeWithNexus_(self, newNexus: Nexus) -> None:
        ...

    # pragma mark NSTableViewDataSource

    def numberOfRowsInTableView_(self, tableView: NSTableView) -> int:
        return 0

    def tableView_objectValueForTableColumn_row_(
        self,
        tableView: NSTableView,
        objectValueForTableColumn: NSObject,
        row: int,
    ) -> str:
        return "uh oh"


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
    @interactionRoot
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
    @interactionRoot
    def pokeIntentionDescription_(self, sender: NSObject) -> None:
        irow = (
            # self.intentionDataSource.tableView_objectValueForTableColumn_row_(
            #     self.intentionsTable, None, 0
            # )
            self.intentionDataSource.rowObjectAt_(0)
        )
        irow.textDescription = "new description"
        irow.title = "new title"

    @interactionRoot
    def awakeFromNib(self) -> None:
        """
        Let's get the GUI started.
        """
        # TODO: update intention data source with initial data from nexus
        self.intentionDataSource.awakeWithNexus_(self.nexus)
        self.streakDataSource.awakeWithNexus_(self.nexus)

        self.debugPalette.setOpaque_(False)
        self.debugPalette.setBackgroundColor_(NSColor.clearColor())
        self.debugPalette.setIsVisible_(True)


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

    NSColor.setIgnoresAlpha_(False)
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
