# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from cProfile import Profile
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import (
    Any,
    Callable,
    ClassVar,
    Dict,
    Iterable,
    Iterator,
    List,
    Optional,
    Tuple,
)

from Foundation import NSIndexSet, NSLog, NSMutableDictionary, NSObject, NSRect
from twisted.internet.base import DelayedCall
from twisted.internet.interfaces import IDelayedCall, IReactorTime
from twisted.python.failure import Failure

import math
from AppKit import (
    NSAlert,
    NSAlertFirstButtonReturn,
    NSAlertSecondButtonReturn,
    NSAlertThirdButtonReturn,
    NSApp,
    NSApplicationDidChangeScreenParametersNotification,
    NSBackingStoreBuffered,
    NSBezierPath,
    NSBorderlessWindowMask,
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
    NSView,
    NSWindow,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorStationary,
)
from dateutil.tz import tzlocal
from objc import IBAction, IBOutlet
from PyObjCTools.AppHelper import callLater

from pomodouroboros.notifs import (
    askForIntent,
    notify,
    setupNotifications,
    withdrawIntentPrompt,
)
from pomodouroboros.pommodel import (
    Break,
    Day,
    Intention,
    IntentionResponse,
    IntentionSuccess,
    Interval,
    Pomodoro,
)
from pomodouroboros.quickapp import Actionable, Status, mainpoint, quit
from pomodouroboros.storage import TEST_MODE, loadOrCreateDay, saveDay


# fillRect = NSBezierPath.fillRect_
fillRect = NSRectFill


class BigProgressView(NSView):
    """
    View that draws a big red/green progress bar rectangle
    """

    _percentage = 0.0
    _leftColor = NSColor.greenColor()
    _rightColor = NSColor.redColor()

    def isOpaque(self) -> bool:
        """
        This view is opaque, try to be faster compositing it
        """
        return True

    @classmethod
    def defaultFocusRingType(self) -> int:
        return NSFocusRingTypeNone

    def setPercentage_(self, newPercentage: float) -> None:
        """
        Set the percentage-full here.
        """
        self._percentage = newPercentage
        self.setNeedsDisplay_(True)
        # self.setNeedsDisplay_(True)

    def setLeftColor_(self, newLeftColor: NSColor) -> None:
        self._leftColor = newLeftColor
        # self.setNeedsDisplay_(True)

    def setRightColor_(self, newRightColor: NSColor) -> None:
        self._rightColor = newRightColor
        # self.setNeedsDisplay_(True)

    def drawRect_(self, rect: NSRect) -> None:
        bounds = self.bounds()
        split = self._percentage * (bounds.size.width)
        NSRectFillListWithColorsUsingOperation(
            [
                NSRect((0, 0), (split, bounds.size.height)),
                NSRect(
                    (split, 0), (bounds.size.width - split, bounds.size.height)
                ),
            ],
            [self._leftColor, self._rightColor],
            2,
            NSCompositingOperationCopy,
        )

    def canBecomeKeyView(self) -> bool:
        return False

    def movableByWindowBackground(self) -> bool:
        return True

    def acceptsFirstMouse_(self, evt: NSEvent) -> bool:
        return True

    def acceptsFirstResponder(self) -> bool:
        return False

    def wantsDefaultClipping(self) -> bool:
        return False


class HUDWindow(NSWindow):
    """
    A window that doesn't receive input events and floats as an overlay.
    """

    def canBecomeKeyWindow(self) -> bool:
        return False

    def canBecomeMainWindow(self) -> bool:
        return False

    def acceptsFirstResponder(self) -> bool:
        return False

    def makeKeyWindow(self) -> None:
        return None


NSModalResponse = int
buttonReturnTo = {
    NSAlertFirstButtonReturn: IntentionSuccess.Achieved,
    NSAlertSecondButtonReturn: IntentionSuccess.Focused,
    NSAlertThirdButtonReturn: IntentionSuccess.Distracted,
}


def getSuccess(intention: Intention) -> IntentionSuccess:
    """
    Show an alert that asks for an evaluation of the success.
    """
    msg = NSAlert.alloc().init()
    msg.addButtonWithTitle_("Achieved it")
    msg.addButtonWithTitle_("Focused on it")
    msg.addButtonWithTitle_("I was distracted")
    msg.setMessageText_("Did you follow your intention?")
    msg.setInformativeText_(
        f"Your intention was: “{intention.description}”.  How did you track to it?"
    )
    msg.layout()
    NSApp().activateIgnoringOtherApps_(True)
    response: NSModalResponse = msg.runModal()
    return buttonReturnTo[response]


def getString(title: str, question: str, defaultValue: str) -> str:
    msg = NSAlert.alloc().init()
    msg.addButtonWithTitle_("OK")
    msg.addButtonWithTitle_("Cancel")
    msg.setMessageText_(title)
    msg.setInformativeText_(question)

    txt = NSTextField.alloc().initWithFrame_(NSRect((0, 0), (200, 100)))
    txt.setMaximumNumberOfLines_(5)
    txt.setStringValue_(defaultValue)
    msg.setAccessoryView_(txt)
    msg.window().setInitialFirstResponder_(txt)
    msg.layout()
    NSApp().activateIgnoringOtherApps_(True)

    response: NSModalResponse = msg.runModal()

    if response == NSAlertFirstButtonReturn:
        return txt.stringValue()
    else:
        return ""


intcb = Callable[["MacPomObserver", Interval, float], None]


@dataclass
class MacPomObserver(object):
    """
    Binding of model notifications interface to mac GUI
    """

    progressView: BigProgressView
    window: HUDWindow
    refreshList: Callable[[], None]
    clock: IReactorTime
    lastThreshold: float = field(default=0.0)
    thresholds: ClassVar[List[Tuple[float, str]]] = [
        (0.25, "Time to get started!"),
        (0.50, "Halfway there."),
        (0.75, "Time to finish up."),
        (0.95, "Almost done!"),
    ]
    active: bool = field(default=False)
    lastIntentionResponse: Optional[IntentionResponse] = None
    baseAlphaValue: float = 0.15
    alphaVariance: float = 0.015
    pulseMultiplier: float = 1.5

    def __post_init__(self):
        self.window.setIsVisible_(self.active)

    def setWindow(self, newWindow: HUDWindow) -> None:
        """
        Change the window to be the new window.
        """
        self.window = newWindow
        newWindow.setIsVisible_(self.active)

    def breakStarting(self, startingBreak: Break) -> None:
        """
        A break is starting.
        """
        self.active = True
        self.window.setIsVisible_(True)
        notify("Starting Break", "Take it easy for a while.")
        self.refreshList()

    def pomodoroStarting(self, day: Day, startingPomodoro: Pomodoro) -> None:
        """
        A pomodoro is starting; time to express an intention.
        """
        self.active = True
        self.lastThreshold = 0.0
        self.window.setIsVisible_(True)
        if (
            startingPomodoro.intention is None
            or startingPomodoro.intention.description is None
        ):

            def doExpressIntention(userText: str) -> None:
                expressIntention(self.clock, day, userText)
                self.refreshList()

            askForIntent(doExpressIntention)
        else:
            notify("Pomodoro Starting", startingPomodoro.intention.description)
        self.refreshList()

    def elapsedWithNoIntention(self, pomodoro: Pomodoro) -> None:
        """
        A pomodoro completed, but no intention was specified.
        """
        notify(
            "Pomodoro Failed",
            informativeText=(
                "The pomodoro elapsed with no intention specified."
            ),
        )
        self.refreshList()

    responses: ClassVar[Dict[IntentionResponse, intcb]] = {}

    def _intention(  # type: ignore
        response: IntentionResponse,
        responses: Dict[IntentionResponse, intcb] = responses,
    ) -> Callable[[intcb], intcb]:
        def decorator(f: intcb) -> intcb:
            responses[response] = f
            return f

        return decorator

    @_intention(IntentionResponse.CanBeSet)
    def _canBeSet(self, interval: Interval, percentageElapsed: float) -> None:
        self.baseAlphaValue = MacPomObserver.baseAlphaValue + 0.1
        self.alphaVariance = MacPomObserver.alphaVariance * 2
        self.pulseMultiplier = MacPomObserver.pulseMultiplier * 2

        self.progressView.setLeftColor_(NSColor.yellowColor())
        self.progressView.setRightColor_(NSColor.purpleColor())
        # boost the urgency on setting an intention

    @_intention(IntentionResponse.AlreadySet)
    def _alreadySet(
        self, interval: Interval, percentageElapsed: float
    ) -> None:
        # Nice soothing "You're doing it!" colors for remembering to set
        # intention
        self.baseAlphaValue = MacPomObserver.baseAlphaValue
        self.pulseMultiplier = MacPomObserver.pulseMultiplier
        self.alphaVariance = MacPomObserver.alphaVariance

        self.progressView.setLeftColor_(NSColor.greenColor())
        self.progressView.setRightColor_(NSColor.blueColor())
        if isinstance(interval, Pomodoro) and interval.intention is not None:
            # TODO: maybe put reminder messages in the model?
            for pct, message in self.thresholds:
                if self.lastThreshold <= pct and percentageElapsed > pct:
                    self.lastThreshold = percentageElapsed
                    notify(
                        "Remember Your Intention",
                        message,
                        "“" + interval.intention.description + "”",
                    )

    @_intention(IntentionResponse.OnBreak)
    def _onBreak(self, interval: Interval, percentageElapsed: float) -> None:
        # Neutral "take it easy" colors for breaks
        self.baseAlphaValue = MacPomObserver.baseAlphaValue
        self.pulseMultiplier = MacPomObserver.pulseMultiplier / 2
        self.alphaVariance = MacPomObserver.alphaVariance / 2

        self.progressView.setLeftColor_(NSColor.lightGrayColor())
        self.progressView.setRightColor_(NSColor.darkGrayColor())

    @_intention(IntentionResponse.TooLate)
    def _tooLate(self, interval: Interval, percentageElapsed: float) -> None:
        self.baseAlphaValue = MacPomObserver.baseAlphaValue
        self.pulseMultiplier = MacPomObserver.pulseMultiplier
        self.alphaVariance = MacPomObserver.alphaVariance

        # Angry "You forgot" colors for setting it too late
        self.progressView.setLeftColor_(NSColor.orangeColor())
        self.progressView.setRightColor_(NSColor.redColor())

    del _intention

    def progressUpdate(
        self,
        interval: Interval,
        percentageElapsed: float,
        canSetIntention: IntentionResponse,
    ) -> None:
        """
        Some time has elapsed on the given interval, and it's now
        percentageElapsed% done.  canSetIntention tells you the likely outcome
        of setting the intention.
        """
        if canSetIntention != self.lastIntentionResponse:
            self.lastIntentionResponse = canSetIntention
            self.responses[canSetIntention](self, interval, percentageElapsed)
            self.refreshList()
        self.progressView.setPercentage_(percentageElapsed)
        alphaValue = (
            math.sin(self.clock.seconds() * self.pulseMultiplier)
            * self.alphaVariance
        ) + self.baseAlphaValue
        self.active = True
        self.window.setIsVisible_(True)
        self.window.setAlphaValue_(alphaValue)

    def dayOver(self):
        """
        The day is over, so there will be no more intervals.
        """
        self.active = False
        self.window.setIsVisible_(False)
        self.refreshList()


def makeOneWindow(contentView) -> HUDWindow:
    app = NSApp()
    mainScreen = NSScreen.mainScreen()
    frame = mainScreen.frame()

    # build args for window initialization:
    #
    # - (instancetype)initWithContentRect:(NSRect)contentRect
    # - styleMask:(NSUInteger)windowStyle
    # - backing:(NSBackingStoreType)bufferingType defer:(BOOL)deferCreation

    height = 50
    padding = 500

    contentRect = NSRect(
        (padding, padding), (frame.size.width - (padding * 2), height)
    )
    styleMask = NSBorderlessWindowMask
    backing = NSBackingStoreBuffered
    defer = False

    win = (
        HUDWindow.alloc()
        .initWithContentRect_styleMask_backing_defer_(
            contentRect,
            styleMask,
            backing,
            defer,
        )
        .retain()
    )
    win.setCollectionBehavior_(
        NSWindowCollectionBehaviorCanJoinAllSpaces
        | NSWindowCollectionBehaviorStationary
    )
    win.setIgnoresMouseEvents_(True)
    win.setAlphaValue_(0.1)
    win.setContentView_(contentView)
    win.setBackgroundColor_(NSColor.blackColor())
    win.setLevel_(NSFloatingWindowLevel)
    win.orderFront_(app)
    return win


def expressIntention(clock: IReactorTime, day: Day, newIntention: str) -> None:
    """
    Express the given intention to the given day.
    """
    intentionResult = day.expressIntention(clock.seconds(), newIntention)
    if intentionResult == IntentionResponse.WasSet:
        notify("Intention Set", f"“{newIntention}”")
    elif intentionResult == IntentionResponse.AlreadySet:
        description = day.pendingIntervals[
            0
        ].intention.description  # type: ignore
        notify(
            "Intention Not Set",
            "Already Specified",
            informativeText=f"intention was already: “{description}”",
        )
    elif intentionResult == IntentionResponse.TooLate:
        notify(
            "Intention Not Set",
            "Too Late",
            informativeText="It's too late to set an intention. "
            "Try again next time!",
        )
    elif intentionResult == IntentionResponse.OnBreak:
        notify(
            "Intention Not Set",
            "You're On Break",
            "Set the intention when the pom begins.",
        )
    else:
        notify(
            "Intention Confusion",
            "Internal Error",
            f"received {intentionResult}",
        )
    saveDay(day)


def setIntention(clock: IReactorTime, day: Day) -> None:
    try:
        newIntention = getString(
            title="Set An Intention",
            question="What is your intention?",
            defaultValue="",
        )
        expressIntention(clock, day, newIntention)
    except BaseException:
        # TODO: roll up error reporting into common event-handler
        print(Failure().getTraceback())


def bonus(when: datetime, day: Day) -> None:
    """
    Start a new pom outside the usual bounds of pomodoro time, either before or
    after the end of the day.
    """
    try:
        day.bonusPomodoro(when)
        saveDay(day)
    except BaseException:
        # TODO: roll up error reporting into common event-handler
        print(Failure().getTraceback())


def nowNative() -> datetime:
    return datetime.now(tz=tzlocal())


from Foundation import (
    NSCalendarUnitYear,
    NSCalendarUnitMonth,
    NSCalendarUnitDay,
    NSCalendarUnitHour,
    NSCalendarUnitMinute,
    NSCalendarUnitSecond,
    NSCalendarUnitNanosecond,
    NSCalendar,
    NSDate,
)

datetimeComponents = (
    NSCalendarUnitYear
    | NSCalendarUnitMonth
    | NSCalendarUnitDay
    | NSCalendarUnitHour
    | NSCalendarUnitMinute
    | NSCalendarUnitSecond
    | NSCalendarUnitNanosecond
)

fromDate = NSCalendar.currentCalendar().components_fromDate_
localOffset = tzlocal()
nsDateNow = NSDate.date
nsDateFromTimestamp = NSDate.dateWithTimeIntervalSince1970_


def localDate(ts: float) -> datetime:
    """
    Use Cocoa to compute a local datetime
    """
    components = fromDate(datetimeComponents, nsDateFromTimestamp(ts))
    return datetime(
        year=components.year(),
        month=components.month(),
        day=components.day(),
        hour=components.hour(),
        minute=components.minute(),
        second=components.second(),
        microsecond=components.nanosecond() // 1000,
        tzinfo=localOffset,
    )


def newDay(forDate: date) -> Day:
    if TEST_MODE:
        return Day.forTesting()
    else:
        return loadOrCreateDay(forDate)


def labelForDay(day: Day) -> str:
    """
    Generate a textual label representing the success proportion of the given
    day.
    """
    score = day.score()
    icon = tomato if score.hits > score.misses else can
    unevaluated, q = (
        (score.unevaluated, "?") if score.unevaluated else ("", "")
    )
    remaining, e = (score.remaining, "…") if score.remaining else ("", "")
    return (
        f"{icon}: {score.hits}✓ {score.misses}✗ {unevaluated}{q}{remaining}{e}"
    )


can = "🥫"
tomato = "🍅"


import traceback


class MenuForwarder(NSResponder):
    """
    Event responder for handling menu keyboard shortcuts defined in the
    status-item menu.
    """

    myMenu: NSMenu = IBOutlet()
    statusMenu: NSMenu = IBOutlet()

    def performKeyEquivalent_(self, event: NSEvent) -> bool:
        for menu in [self.statusMenu, self.myMenu]:
            handled = menu.performKeyEquivalent_(event)
            if handled:
                return True
        return super().performKeyEquivalent_(event)


@dataclass
class DayManager(object):
    observer: MacPomObserver
    window: HUDWindow
    progress: BigProgressView
    reactor: IReactorTime
    editController: DayEditorController
    day: Day = field(default_factory=lambda: newDay(date.today()))
    screenReconfigurationTimer: Optional[IDelayedCall] = None
    profile: Optional[Profile] = None

    @classmethod
    def new(cls, reactor, editController) -> DayManager:
        progressView = BigProgressView.alloc().init()
        window = makeOneWindow(progressView)

        def listRefresher() -> None:
            if editController.editorWindow.isVisible():
                editController.refreshStatus_(self)

        observer = MacPomObserver(progressView, window, listRefresher, reactor)
        self = cls(
            observer,
            window,
            progressView,
            reactor,
            editController,
        )
        return self

    def screensChanged(self) -> None:
        def recreateWindow():
            self.screenReconfigurationTimer = None
            newWindow = makeOneWindow(self.progress)
            self.observer.setWindow(newWindow)
            self.window, oldWindow = newWindow, self.window
            oldWindow.close()

        settleDelay = 3.0
        if self.screenReconfigurationTimer is None:
            self.screenReconfigurationTimer = self.reactor.callLater(
                settleDelay, recreateWindow
            )
        else:
            self.screenReconfigurationTimer.reset(settleDelay)

    def startProfiling(self) -> None:
        """
        start profiling the python
        """
        self.profile = Profile()
        self.profile.enable()

    def stopProfiling(self) -> None:
        """
        stop the profiler and show some stats
        """
        assert self.profile is not None
        self.profile.disable()
        profile: Optional[Profile]
        profile, self.profile = self.profile, None
        assert profile is not None
        profile.dump_stats(os.path.expanduser("~/pom.pstats"))

    def addBonusPom(self) -> None:
        bonus(localDate(self.reactor.seconds()), self.day)
        self.observer.refreshList()

    def doSetIntention(self) -> None:
        setIntention(self.reactor, self.day)
        self.observer.refreshList()

    def start(self) -> None:
        status = Status(can)

        def doList():
            self.editController.editorWindow.setIsVisible_(True)
            self.editController.refreshStatus_(self)
            NSApp().activateIgnoringOtherApps_(True)

        def raiseException():
            # from Foundation import NSException
            # NSException.raise_format_("SampleException", "a thing happened")
            raise Exception("report this pls")

        status.menu(
            [
                ("Intention", self.doSetIntention),
                (
                    "Bonus Pomodoro",
                    self.addBonusPom,
                ),
                ("Evaluate", lambda: self.setSuccess()),
                ("Start Profiling", lambda: self.startProfiling()),
                ("Finish Profiling", lambda: self.stopProfiling()),
                ("List Pomodoros", doList),
                ("Break", raiseException),
                ("Quit", quit),
            ]
        )

        mf = MenuForwarder.alloc().init()

        mf.statusMenu = status.item.menu()

        (
            NSNib.alloc()
            .initWithNibNamed_bundle_("StandardMenus.nib", None)
            .instantiateWithOwner_topLevelObjects_(mf, None)
        )

        # TODO: this is wrong, we need the window to dispatch to the menus
        # directly in sendEvent_ because we aren't the next responder when a
        # table edit cell is focused for some reason (even though we are when
        # the table is receiving key events to move the selection around?)
        NSApp().keyEquivalentHandler = mf

        def update() -> None:
            try:
                try:
                    currentTimestamp = self.reactor.seconds()
                    # presentDate = localDate(currentTimestamp).date()
                    presentDate = date.today()
                    if presentDate != self.day.startTime.date():
                        self.day = newDay(presentDate)
                    self.day.advanceToTime(currentTimestamp, self.observer)
                    label = labelForDay(self.day)
                    if TEST_MODE:
                        label = "🐇" + label
                    status.item.setTitle_(label)
                except BaseException:
                    print(Failure().getTraceback())
            finally:
                # trying to stick to 1% CPU...
                finishTime = self.reactor.seconds()
                self.reactor.callLater(
                    (finishTime - currentTimestamp) * 75, update
                )

        update()

    def setSuccess(self) -> None:
        pomsToEvaluate = self.day.unEvaluatedPomodoros()
        if not pomsToEvaluate:
            notify("No Evaluations Pending")
            notify("You've already evaluated everything you can.")
            return
        aPom = pomsToEvaluate[0]
        # todo: teach mypy about this
        assert (
            aPom.intention is not None
        ), "unEvaluatedPomodoros scans this already"
        succeeded = getSuccess(aPom.intention)
        self.day.evaluateIntention(aPom, succeeded)
        saveDay(self.day)
        didIt = aPom.intention.wasSuccessful not in (
            False,
            IntentionSuccess.Distracted,
            IntentionSuccess.NeverEvaluated,
        )
        adjective = "successful" if didIt else "failed"
        noun = "success" if didIt else "failure"
        self.observer.refreshList()
        notify(
            f"pomodoro {noun}".title(),
            informativeText=f"Marked Pomodoro {adjective}.",
        )
        return


def callOnNotification(nsNotificationName: str, f: Callable[[], None]):
    NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
        Actionable.alloc().initWithFunction_(f).retain(),
        "doIt:",
        nsNotificationName,
        None,
    )


class DescriptionChanger(NSObject):
    observing = False

    def initWithDayManager_andController_(
        self, mgr: DayManager, ctrl: DayEditorController
    ) -> DescriptionChanger:
        self.mgr = mgr
        self.day = mgr.day
        self.ctrl = ctrl
        return self

    @contextmanager
    def ignoreChanges(self) -> Iterator[None]:
        self.observing = True
        try:
            yield
        finally:
            self.observing = False

    def observeValueForKeyPath_ofObject_change_context_(
        self,
        keyPath: str,
        ofObject: Dict[str, Any],
        change: Dict[str, Any],
        context,
    ) -> None:
        if change.get("notificationIsPrior"):
            return
        if self.observing:
            return
        with self.ignoreChanges():
            assert keyPath == "description"
            pom: Pomodoro = ofObject["pom"]
            newDescription: str = change["new"]
            result = self.day.expressIntention(
                self.mgr.reactor.seconds(), newDescription, pom
            )
            callLater(0.0, lambda: self.ctrl.refreshStatus_(self.mgr))
            saveDay(self.day)


class DayEditorController(NSObject):
    arrayController = IBOutlet()
    editorWindow = IBOutlet()
    tableView = IBOutlet()
    observer = None

    @IBAction
    def hideMe_(self, sender) -> None:
        self.editorWindow.setIsVisible_(False)

    def initWithClock_(self, clock: IReactorTime) -> DayEditorController:
        self.clock = clock
        return self

    def refreshStatus_(self, dayManager: DayManager) -> None:
        previouslySelectedRow = self.tableView.selectedRow()
        oldObserver = self.observer
        if oldObserver is not None:
            for eachPreviousDict in self.arrayController.arrangedObjects():
                eachPreviousDict.removeObserver_forKeyPath_(
                    oldObserver, "description"
                )
        observer = (
            self.observer
        ) = DescriptionChanger.alloc().initWithDayManager_andController_(
            dayManager, self
        )
        now = self.clock.seconds()
        hasCurrent = False
        with observer.ignoreChanges():
            self.arrayController.removeObjects_(
                list(self.arrayController.arrangedObjects())
            )
            for i, pomOrBreak in enumerate(
                [
                    each
                    for each in dayManager.day.elapsedIntervals
                    + dayManager.day.pendingIntervals
                    if isinstance(each, Pomodoro)
                ],
                start=1,
            ):
                # todo: bind editability to one of these attributes so we can
                # control it on a per-row basis
                desc = (
                    pomOrBreak.intention.description or ""
                    if pomOrBreak.intention is not None
                    else ""
                )
                canChange = (now < pomOrBreak.startTimestamp) or (
                    (pomOrBreak.intention is None)
                    and (
                        now
                        < (
                            pomOrBreak.startTimestamp
                            + dayManager.day.intentionGracePeriod
                        )
                    )
                )
                if not canChange:
                    desc = "🔒 " + desc

                isCurrent = False
                if not hasCurrent:
                    if now < pomOrBreak.endTimestamp:
                        hasCurrent = isCurrent = True

                rowDict = NSMutableDictionary.dictionaryWithDictionary_(
                    {
                        "index": f"{i}{'→' if isCurrent else ''}",
                        "startTime": pomOrBreak.startTime.time().isoformat(
                            timespec="minutes"
                        ),
                        "endTime": pomOrBreak.endTime.time().isoformat(
                            timespec="minutes"
                        ),
                        "description": desc,
                        "success": (
                            "❌" if now > pomOrBreak.endTimestamp else "…"
                        )
                        if pomOrBreak.intention is None
                        else {
                            None: "…"
                            if now < pomOrBreak.startTimestamp
                            else "📝",
                            IntentionSuccess.Achieved: "✅",
                            IntentionSuccess.Focused: "🤔",
                            IntentionSuccess.Distracted: "🦋",
                            IntentionSuccess.NeverEvaluated: "👋",
                            True: "✅",
                            False: "🦋",
                        }[pomOrBreak.intention.wasSuccessful],
                        "pom": pomOrBreak,
                    }
                )
                self.arrayController.addObject_(rowDict)
                rowDict.addObserver_forKeyPath_options_context_(
                    observer, "description", 0xF, 0x020202
                )
        self.tableView.reloadData()
        self.tableView.selectRowIndexes_byExtendingSelection_(
            NSIndexSet.indexSetWithIndex_(previouslySelectedRow), False
        )


@mainpoint()
def main(reactor: IReactorTime) -> None:
    import traceback, sys

    ctrl = DayEditorController.alloc().initWithClock_(reactor)
    stuff = list(
        NSNib.alloc()
        .initWithNibNamed_bundle_("GoalListWindow.nib", None)
        .instantiateWithOwner_topLevelObjects_(ctrl, None)
    )
    setupNotifications()
    withdrawIntentPrompt()
    dayManager = DayManager.new(reactor, ctrl)
    ctrl.refreshStatus_(dayManager)
    dayManager.start()
    callOnNotification(
        NSApplicationDidChangeScreenParametersNotification,
        dayManager.screensChanged,
    )
