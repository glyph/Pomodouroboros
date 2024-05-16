from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import TYPE_CHECKING, Iterator, Sequence

import objc
from AppKit import NSTableView
from Foundation import NSColor, NSObject
from objc import IBAction, IBOutlet, super

from ..model.boundaries import EvaluationResult
from ..model.debugger import debug
from ..model.intention import Intention
from ..model.intervals import Pomodoro
from ..model.nexus import Nexus
from ..model.util import interactionRoot, showFailures
from .mac_dates import LOCAL_TZ
from .mac_utils import Attr, Forwarder
from .model_convert import ModelConverter


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
        self.computeStatus()
        return self

    # pragma mark Attributes

    _forwarded = Forwarder(
        "intention", setterWrapper=interactionRoot
    ).forwarded

    title: Attr[str, IntentionRow] = _forwarded("title")
    textDescription: Attr[str, IntentionRow] = _forwarded("description")

    def computeStatus(self) -> None:
        """
        Set a status emoji based on the current completion/abandonment status
        of this intention.
        """
        result = ""
        if self.intention.completed:
            result = "✅"
        if self.intention.abandoned:
            result = "🪦"
        debug(
            "getting status",
            self.intention.completed,
            self.intention.abandoned,
            result,
        )
        self.status = result

    nexus: Nexus = objc.object_property()
    intention: Intention = objc.object_property()
    shouldHideEstimate = objc.object_property()
    canEditSummary = objc.object_property()
    hasColor = objc.object_property()
    colorValue = objc.object_property()
    estimate = objc.object_property()
    creationText = objc.object_property()
    modificationText = objc.object_property()
    status = objc.object_property()

    del _forwarded

    # pragma mark Accessors & Mutators

    @colorValue.getter
    def _getColorValue(self) -> NSColor:
        return self._colorValue

    @colorValue.setter
    @interactionRoot
    def _setColorValue(self, colorValue: NSColor) -> None:
        debug("setting", colorValue)
        self._colorValue = colorValue
        debug("set", colorValue)

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


class IntentionDataSource(NSObject):
    """
    NSTableViewDataSource for the list of intentions.
    """

    # pragma mark Attributes

    intentionRowMap: ModelConverter[
        Intention, IntentionRow
    ] = objc.object_property()
    nexus: Nexus | None = objc.object_property()

    selectedIntention: IntentionRow | None = objc.object_property()
    "everything in the detail view is bound to this"

    hasNoSelection: bool = objc.object_property()
    "detail view's 'hidden' is bound to this"

    canStartPomodoro: bool = objc.object_property()
    canAbandonIntention: bool = objc.object_property()

    # kept in sync by MacUserInterface, this indicates whether an interval that
    # would block the start of a new Pomodoro (Pomodoro, Break) is currently
    # running
    blockingIntervalRunning: bool = objc.object_property()

    pomsData: IntentionPomodorosDataSource
    pomsData = IBOutlet()

    pomsTable: NSTableView
    pomsTable = IBOutlet()

    intentionsTable: NSTableView
    intentionsTable = IBOutlet()

    # pragma mark Initialization and awakening

    def init(self) -> IntentionDataSource:
        """
        Construct an L{IntentionDataSource}.  This is constructed in the nib.
        """
        self.hasNoSelection = True
        self.selectedIntention = None
        self.canStartPomodoro = False
        self.canAbandonIntention = False
        return self

    def awakeWithNexus_(self, newNexus: Nexus) -> None:
        """
        Complete initialization after awakeFromNib by associating everything
        with a 'nexus'.
        """
        self.nexus = newNexus
        self.pomsData.nexus = newNexus

        @ModelConverter
        def translator(intention: Intention) -> IntentionRow:
            assert self.nexus is not None, "what"
            return IntentionRow.alloc().initWithIntention_andNexus_(
                intention, self.nexus
            )

        self.intentionRowMap = translator
        self.recalculate()

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
        debug("SELECTION CHANGED:", notification.object().selectedRowIndexes())
        self.recalculate()

    def startingBlocked(self) -> None:
        self.blockingIntervalRunning = True
        self.recalculate()

    def startingUnblocked(self) -> None:
        self.blockingIntervalRunning = False
        self.recalculate()

    def recalculate(self) -> None:
        """
        Recompute various UI-state attributes after the selection changes, like whether we can start a
        pomodoro, whether we can abandon the selected intention, etc.
        """
        if self.intentionsTable is None:
            debug("recalculate before awake?")
            return
        idx: int = self.intentionsTable.selectedRow()

        if idx == -1:
            self.selectedIntention = None
            self.hasNoSelection = True
            self.canStartPomodoro = False
            self.canAbandonIntention = False
            return

        self.selectedIntention = self.rowObjectAt_(idx)
        selected = self.selectedIntention
        selected.computeStatus()
        intention = selected.intention

        self.pomsData.backingData = intention.pomodoros
        self.pomsData.clearSelection()
        self.pomsTable.reloadData()
        self.hasNoSelection = False
        self.canStartPomodoro = (
            (not intention.abandoned)
            and (not intention.completed)
            and (not self.blockingIntervalRunning)
        )
        self.canAbandonIntention = (not intention.abandoned) and (
            not intention.completed
        )

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


@contextmanager
def refreshedData(*tables: NSTableView) -> Iterator[None]:
    selections = [table.selectedRowIndexes() for table in tables]
    debug("all selections saved:", selections)
    yield
    debug("restoring all selections")
    for table, selection in zip(tables, selections):
        table.reloadData()
        debug("restoring selection", table, selection)
        table.selectRowIndexes_byExtendingSelection_(selection, False)
    debug("restored all selections")


class IntentionPomodorosDataSource(NSObject):
    # pragma mark NSTableViewDataSource
    backingData: Sequence[Pomodoro] = []
    selectedPomodoro: Pomodoro | None = None
    nexus: Nexus

    intentionPomsTable: NSTableView
    intentionPomsTable = IBOutlet()

    intentionsTable: NSTableView
    intentionsTable = IBOutlet()

    allIntentionsSource: IntentionDataSource
    allIntentionsSource = IBOutlet()

    # active states for buttons
    canEvaluateDistracted: bool = objc.object_property()
    canEvaluateInterrupted: bool = objc.object_property()
    canEvaluateFocused: bool = objc.object_property()
    canEvaluateAchieved: bool = objc.object_property()

    def init(self) -> IntentionPomodorosDataSource:
        self.hasSelection = False
        return self

    def numberOfRowsInTableView_(self, tableView: NSTableView) -> int:
        return len(self.backingData)

    def tableView_objectValueForTableColumn_row_(
        self,
        tableView: NSTableView,
        tableColumn: object,
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
            "startTime": str(dt.time().replace(microsecond=0)),
            "endTime": str(et.time().replace(microsecond=0)),
            "evaluation": ""
            if e is None
            else {
                EvaluationResult.distracted: "🦋",
                EvaluationResult.interrupted: "🗣",
                EvaluationResult.focused: "🤔",
                EvaluationResult.achieved: "✅",
            }[e.result],
            # TODO: should be a clickable link to the session that this was in,
            # but first we need that feature from the model.
            "inSession": "???",
        }

    def clearSelection(self) -> None:
        debug("CLEARING SELECTION/intpom data!")
        self.selectedPomodoro = None
        self.hasSelection = False
        self.canEvaluateDistracted = (
            self.canEvaluateInterrupted
        ) = self.canEvaluateFocused = self.canEvaluateAchieved = False

    # pragma mark NSTableViewDelegate
    @interactionRoot
    def tableViewSelectionDidChange_(self, notification: NSObject) -> None:
        tableView = notification.object()
        idx: int = tableView.selectedRow()
        debug("selection CLEAR CHECK", idx, tableView.selectedRowIndexes())
        if idx == -1:
            self.clearSelection()
            return

        self.selectedPomodoro = self.backingData[idx]
        self.canEvaluateDistracted = True
        self.canEvaluateInterrupted = True
        self.canEvaluateFocused = True
        # should also update this last one when reloading data?
        self.canEvaluateAchieved = idx == (len(self.backingData) - 1)

    def doEvaluate_(self, er: EvaluationResult):
        assert (
            self.selectedPomodoro is not None
        ), "must have a pomodorodo selected and the UI should be enforcing that"
        with refreshedData(self.intentionsTable, self.intentionPomsTable):
            self.nexus.evaluatePomodoro(self.selectedPomodoro, er)
            self.allIntentionsSource.recalculate()

    @IBAction
    @interactionRoot
    def distractedClicked_(self, sender: NSObject) -> None:
        self.doEvaluate_(EvaluationResult.distracted)

    @IBAction
    @interactionRoot
    def interruptedClicked_(self, sender: NSObject) -> None:
        self.doEvaluate_(EvaluationResult.interrupted)

    @IBAction
    @interactionRoot
    def focusedClicked_(self, sender: NSObject) -> None:
        self.doEvaluate_(EvaluationResult.focused)

    @IBAction
    @interactionRoot
    def achievedClicked_(self, sender: NSObject) -> None:
        self.doEvaluate_(EvaluationResult.achieved)
