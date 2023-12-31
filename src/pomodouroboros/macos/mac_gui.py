from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeVar

from AppKit import (
    NSApplication,
    NSColor,
    NSNib,
    NSTableView,
    NSTextField,
    NSWindow,
)
from Foundation import NSIndexSet, NSObject
from objc import IBAction, IBOutlet
from quickmacapp import Status, answer, mainpoint
from twisted.internet.defer import Deferred
from twisted.internet.interfaces import IReactorTime
from twisted.internet.task import LoopingCall

from ..model.debugger import debug
from ..model.intention import Estimate, Intention
from ..model.intervals import (
    AnyInterval,
    Break,
    GracePeriod,
    Pomodoro,
    StartPrompt,
)
from ..model.nexus import Nexus
from ..model.observables import Changes, IgnoreChanges, SequenceObserver
from ..model.storage import loadDefaultNexus
from ..model.util import interactionRoot, intervalSummary, showFailures
from ..storage import TEST_MODE

from .intentions_gui import IntentionDataSource
from .mac_utils import SometimesBackground
from .multiple_choice import multipleChoiceButtons
from .old_mac_gui import main as oldMain
from .progress_hud import ProgressController
from .sessions_gui import SessionDataSource
from .text_fields import HeightSizableTextField, makeMenuLabel

lightPurple = NSColor.colorWithSRGBRed_green_blue_alpha_(0.7, 0.0, 0.7, 1.0)
darkPurple = NSColor.colorWithSRGBRed_green_blue_alpha_(0.5, 0.0, 0.5, 1.0)


@dataclass
class MacUserInterface:
    """
    UI for the Mac.
    """

    pc: ProgressController
    clock: IReactorTime
    nexus: Nexus
    explanatoryLabel: HeightSizableTextField
    intentionDataSource: IntentionDataSource
    currentInterval: AnyInterval | None = None

    def startPromptUpdate(self, startPrompt: StartPrompt) -> None:
        """
        You're in a start prompt, update the description to explain to the user
        what should happen next.
        """
        self.setExplanation(
            # TODO: this should be in the model somewhere, not ad-hoc in the
            # middle of one frontend
            f"{startPrompt.pointsBeforeLoss} possible points remain\n\n"
            f"but in {intervalSummary(int(startPrompt.endTime - self.clock.seconds()))}\n"
            f"you'll lose {startPrompt.pointsLost:g} possible points."
            "\n\nStart a Pomodoro now with ⌘⌥⌃P !"
        )

    def describeCurrentState(self, description: str) -> None:
        ...

    def intervalStart(self, interval: AnyInterval) -> None:
        self.currentInterval = interval
        match interval:
            case StartPrompt():
                self.pc.setColors(NSColor.redColor(), NSColor.darkGrayColor())
                self.startPromptUpdate(interval)
                self.intentionDataSource.startingUnblocked()
            case Pomodoro(intention=x):
                self.pc.setColors(NSColor.greenColor(), NSColor.blueColor())
                self.setExplanation(f"Work on Pomodoro: «{x.title}»")
                self.intentionDataSource.startingBlocked()
            case Break():
                self.setExplanation("Take a break.")
                self.pc.setColors(
                    NSColor.lightGrayColor(), NSColor.darkGrayColor()
                )
                self.intentionDataSource.startingBlocked()
            case GracePeriod():
                self.intentionDataSource.startingUnblocked()
                self.setExplanation("Keep your streak going!")
                self.pc.setColors(
                    lightPurple,
                    darkPurple,
                )
        self.pc.immediateReticleUpdate(self.clock)

    def intervalProgress(self, percentComplete: float) -> None:
        match self.currentInterval:
            case StartPrompt():
                self.startPromptUpdate(self.currentInterval)
        self.pc.animatePercentage(self.clock, percentComplete)

    def intervalEnd(self) -> None:
        self.intentionDataSource.startingUnblocked()

    def intentionListObserver(self) -> SequenceObserver[Intention]:
        """
        Return a change observer for the full list of L{Intention}s.
        """
        return IgnoreChanges

    def intentionObjectObserver(
        self, intention: Intention
    ) -> Changes[str, object]:
        """
        Return a change observer for the given L{Intention}.
        """
        return IgnoreChanges

    def intentionPomodorosObserver(
        self, intention: Intention
    ) -> SequenceObserver[Pomodoro]:
        """
        Return a change observer for the given L{Intention}'s list of
        pomodoros.
        """
        return IgnoreChanges

    def intentionEstimatesObserver(
        self, intention: Intention
    ) -> SequenceObserver[Estimate]:
        """
        Return a change observer for the given L{Intention}'s list of
        estimates.
        """
        return IgnoreChanges

    def intervalObserver(self, interval: AnyInterval) -> Changes[str, object]:
        """
        Return a change observer for the given C{interval}.
        """
        return IgnoreChanges

    def setExplanation(self, explanatoryText: str) -> None:
        """
        Change the explanatory text of the menu label to explain what is going
        on so the user can see what the deal is.
        """
        self.pc.setReticleText(explanatoryText)
        self.explanatoryLabel.setStringValue_(explanatoryText)
        self.explanatoryLabel.setNeedsDisplay_(True)
        for repeat in range(3):
            self.explanatoryLabel.setFrameSize_(
                self.explanatoryLabel.intrinsicContentSize()
            )

    @classmethod
    def build(cls, nexus: Nexus, clock: IReactorTime) -> MacUserInterface:
        """
        Create a MacUserInterface and all its constituent widgets.
        """
        owner: PomFilesOwner = (
            PomFilesOwner.alloc().initWithNexus_(nexus).retain()
        )
        nibInstance = NSNib.alloc().initWithNibNamed_bundle_(
            "IntentionEditor.nib", None
        )
        nibInstance.instantiateWithOwner_topLevelObjects_(owner, None)
        pc = ProgressController()
        SometimesBackground(
            owner.intentionsWindow, pc.redisplay
        ).startObserving()

        def openWindow() -> None:
            owner.intentionsWindow.makeKeyAndOrderFront_(owner)
            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

        status = Status("🍅🔰")
        status.menu([("Open Window", openWindow)])
        self = cls(
            pc,
            clock,
            nexus,
            makeMenuLabel(status.item.menu()),
            owner.intentionDataSource,
        )
        self.setExplanation("Starting Up...")
        return self


T = TypeVar("T")
U = TypeVar("U")
S = TypeVar("S")


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
    sessionDataSource: SessionDataSource
    sessionDataSource = IBOutlet()

    intentionDataSource = IBOutlet()  # type: IntentionDataSource
    streakDataSource = IBOutlet()  # type: StreakDataSource

    intentionsWindow: NSWindow
    intentionsWindow = IBOutlet()

    intentionsTable: NSTableView
    intentionsTable = IBOutlet()

    intentionsTitleField: NSTextField
    intentionsTitleField = IBOutlet()

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

    def showButton_(self, sender: NSObject) -> None:
        debug("button", sender.title())

    @IBAction
    def quickChooseIntention_(self, sender: NSObject) -> None:
        pass

    @IBAction
    def addStackButton_(self, sender: NSObject) -> None:
        async def getButton() -> None:
            result = await multipleChoiceButtons(
                [
                    (NSColor.redColor(), "red", 10),
                    (NSColor.orangeColor(), "orange", 11),
                    (NSColor.yellowColor(), "yellow", 12),
                    (NSColor.greenColor(), "green", 13),
                    (NSColor.blueColor(), "blue", 14),
                    (NSColor.systemIndigoColor(), "indigo", 15),
                    (NSColor.purpleColor(), "purple", 16),
                ]
            )
            await answer("choice complete", f"result was {result}")

        with showFailures():
            Deferred.fromCoroutine(getButton())

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
        self.intentionsWindow.makeFirstResponder_(self.intentionsTitleField)

    @IBAction
    @interactionRoot
    def startSelectedIntention_(self, sender: NSObject) -> None:
        """
        Start a pomodoro using the selected intention.
        """
        intent = self.intentionDataSource.selectedIntention
        assert intent is not None, "how did you get here"
        self.nexus.startPomodoro(intent.intention)

    @IBAction
    @interactionRoot
    def abandonSelectedIntention_(self, sender: NSObject) -> None:
        """
        Abandon the selected intention
        """
        intent = self.intentionDataSource.selectedIntention
        assert intent is not None, "how did you get here"
        intent.intention.abandoned = True
        debug("set intention abandoned", intent.intention)
        self.intentionDataSource.recalculate()

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
        with showFailures():
            # self.addStackButton_(self)
            # TODO: update intention data source with initial data from nexus
            self.intentionDataSource.awakeWithNexus_(self.nexus)
            self.streakDataSource.awakeWithNexus_(self.nexus)
            if (
                self.intentionDataSource.numberOfRowsInTableView_(
                    self.intentionsTable
                )
                > 0
            ):
                self.intentionsTable.selectRowIndexes_byExtendingSelection_(
                    NSIndexSet.indexSetWithIndex_(0),
                    False,
                )


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
    theNexus.addManualSession(
        reactor.seconds() + 1.0, reactor.seconds() + 1000.0
    )

    def doAdvance() -> None:
        theNexus.advanceToTime(reactor.seconds())

    LoopingCall(doAdvance).start(3.0, now=True)

    if TEST_MODE:
        # When I'm no longer bootstrapping the application I'll want to *not*
        # unconditionally activate here, just have normal launch behavior.
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
