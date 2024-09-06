from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from typing import TYPE_CHECKING, Callable, TypeVar
from zoneinfo import ZoneInfo

from AppKit import (
    NSApplication,
    NSColor,
    NSNib,
    NSTableView,
    NSTextField,
    NSWindow,
)
from datetype import aware
from Foundation import NSIndexSet, NSObject
from fritter.drivers.datetimes import guessLocalZone
from objc import IBAction, IBOutlet, object_property, super
from quickmacapp import Status, answer, mainpoint
from twisted.internet.defer import Deferred
from twisted.internet.interfaces import IReactorTime
from twisted.internet.task import LoopingCall

from pomodouroboros.macos.progress_hud import PieTimer

from ..model.debugger import debug
from ..model.intention import Estimate, Intention
from ..model.intervals import (
    AnyIntervalOrIdle,
    Break,
    GracePeriod,
    Pomodoro,
    StartPrompt,
)
from ..model.nexus import Nexus
from ..model.observables import Changes, IgnoreChanges, SequenceObserver
from ..model.sessions import DailySessionRule, Weekday, Session
from ..model.storage import loadDefaultNexus
from ..model.util import (
    AMPM,
    addampm,
    ampmify,
    interactionRoot,
    intervalSummary,
    showFailures,
)
from ..storage import TEST_MODE
from .hudmulti import debugMultiHud
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
    currentInterval: AnyIntervalOrIdle

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

    def describeCurrentState(self, description: str) -> None: ...

    def sessionStarted(self, session: Session) -> None:
        "TODO"

    def sessionEnded(self):
        "TODO"

    def intervalStart(self, interval: AnyIntervalOrIdle) -> None:
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

    def intervalObserver(
        self, interval: AnyIntervalOrIdle
    ) -> Changes[str, object]:
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
            nexus._activeInterval,  # TODO: that seems wrong
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


class DebugDataContainer(NSObject):
    debugPercentage: float = object_property()
    debugBonus1: float = object_property()
    debugBonus2: float = object_property()

    myPieTimer: PieTimer
    myPieTimer = IBOutlet()
    myOtherPieTimer: PieTimer
    myOtherPieTimer = IBOutlet()

    def init(self) -> DebugDataContainer:
        self.debugPercentage = 0.0
        return self

    def awakeFromNib(self) -> None:
        for eachPieTimer in [self.myPieTimer, self.myOtherPieTimer]:
            eachPieTimer.bind_toObject_withKeyPath_options_(
                "percentage",
                self,
                "debugPercentage",
                None,
            )
            eachPieTimer.bind_toObject_withKeyPath_options_(
                "bonusPercentage1",
                self,
                "debugBonus1",
                None,
            )
            eachPieTimer.bind_toObject_withKeyPath_options_(
                "bonusPercentage2",
                self,
                "debugBonus2",
                None,
            )


class StreakDataSource(NSObject):
    """
    NSTableViewDataSource for the list of streaks.
    """

    # backingData: Sequence[Streak]

    def awakeWithNexus_(self, newNexus: Nexus) -> None: ...

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


def showMeSetter(name: str) -> Callable[[AutoStreakRuleValues, object], None]:

    def aSetter(self: AutoStreakRuleValues, value: object) -> None:

        print(f"setting {name} to {value}")
        # follow object_property naming convention for storage attribute
        # (i.e. prefix underscore)
        setattr(self, f"_{name}", value)

        if self.awoken:
            print(self.synthesizeRule())

    return aSetter


TZ = guessLocalZone()
defaultRule = DailySessionRule(
    aware(time(9, 0, tzinfo=TZ), ZoneInfo),
    aware(time(5 + 12, 0, tzinfo=TZ), ZoneInfo),
    days={
        Weekday.monday,
        Weekday.tuesday,
        Weekday.wednesday,
        Weekday.thursday,
        Weekday.friday,
    },
)


class AutoStreakRuleValues(NSObject):
    sundaySet: bool = object_property()
    mondaySet: bool = object_property()
    tuesdaySet: bool = object_property()
    wednesdaySet: bool = object_property()
    thursdaySet: bool = object_property()
    fridaySet: bool = object_property()
    saturdaySet: bool = object_property()

    startHour: int = object_property()
    startMinute: int = object_property()
    startAMPM: AMPM = object_property()

    endHour: int = object_property()
    endMinute: int = object_property()
    endAMPM: AMPM = object_property()

    shouldAutoStart = object_property()

    _relevantAttributes = []

    for aname in dir():
        if aname.startswith("_"):
            continue
        _relevantAttributes.append(aname)
        locals()[aname].setter(showMeSetter(aname))
    del aname

    awoken = object_property()

    def awakeFromNib(self) -> None:
        super().awakeFromNib()
        for attribute in self._relevantAttributes:
            if getattr(self, attribute) is None:
                self.absorbRule_(defaultRule)
        self.awoken = True

    def absorbRule_(self, rule: DailySessionRule) -> None:
        try:
            awoken, self.awoken = self.awoken, False
            for enumerated in Weekday:
                setattr(self, enumerated.name + "Set", enumerated in rule.days)
            startHour, startAMPM = addampm(rule.dailyStart.hour)
            self.startHour, self.startMinute, self.startAMPM = (
                startHour,
                rule.dailyStart.minute,
                startAMPM,
            )
            endHour, endAMPM = addampm(rule.dailyEnd.hour)
            self.endHour, self.endMinute, self.endAMPM = (
                endHour,
                rule.dailyEnd.minute,
                endAMPM,
            )
        finally:
            self.awoken = awoken

    def synthesizeRule(self) -> DailySessionRule:
        days = set()
        for enumerated in Weekday:
            if getattr(self, enumerated.name + "Set"):
                days.add(enumerated)
        return DailySessionRule(
            aware(
                time(
                    hour=ampmify(self.startHour, self.startAMPM),
                    minute=self.startMinute,
                    tzinfo=TZ,
                ),
                ZoneInfo,
            ),
            aware(
                time(
                    hour=ampmify(self.endHour, self.endAMPM),
                    minute=self.endMinute,
                    tzinfo=TZ,
                ),
                ZoneInfo,
            ),
            days=days,
        )


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

    autoStreakRuleValues: AutoStreakRuleValues
    autoStreakRuleValues = IBOutlet()

    if TYPE_CHECKING:

        @classmethod
        def alloc(self) -> PomFilesOwner: ...

    def initWithNexus_(self, nexus: Nexus) -> PomFilesOwner:
        """
        Initialize a pomfilesowner with a nexus
        """
        self.nexus = nexus
        return self

    def showButton_(self, sender: NSObject) -> None:
        debug("button", sender.title())

    @IBAction
    def hudDebugButton_(self, sender: NSObject) -> None:
        debugMultiHud()

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
        self.nexus.addIntention()
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
            self.sessionDataSource.awakeWithNexus_(self.nexus)
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

    def doAdvance() -> None:
        theNexus.advanceToTime(reactor.seconds())

    LoopingCall(doAdvance).start(3.0, now=True)

    if TEST_MODE:
        # When I'm no longer bootstrapping the application I'll want to *not*
        # unconditionally activate here, just have normal launch behavior.
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
