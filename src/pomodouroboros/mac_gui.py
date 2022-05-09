# -*- coding: utf-8 -*-
from __future__ import annotations

from cProfile import Profile
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime
from time import time as rawSeconds
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

from Foundation import NSLog, NSMutableDictionary, NSObject, NSRect
from twisted.internet.base import DelayedCall
from twisted.internet.interfaces import IReactorTCP
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
from objc import IBAction, IBOutlet  # type: ignore
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
        print("post-init", self.active)
        self.window.setIsVisible_(self.active)

    def setWindow(self, newWindow: HUDWindow) -> None:
        """
        Change the window to be the new window.
        """
        self.window = newWindow
        print("set-window", self.active)
        newWindow.setIsVisible_(self.active)

    def breakStarting(self, startingBreak: Break) -> None:
        """
        A break is starting.
        """
        print("break start")
        self.active = True
        self.window.setIsVisible_(True)
        notify("Starting Break", "Take it easy for a while.")

    def pomodoroStarting(self, day: Day, startingPomodoro: Pomodoro) -> None:
        """
        A pomodoro is starting; time to express an intention.
        """
        print("pom start")
        self.active = True
        self.lastThreshold = 0.0
        self.window.setIsVisible_(True)
        askForIntent(lambda userText: expressIntention(day, userText))

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
        self.progressView.setPercentage_(percentageElapsed)
        alphaValue = (
            math.sin(rawSeconds() * self.pulseMultiplier) * self.alphaVariance
        ) + self.baseAlphaValue
        self.active = True
        self.window.setIsVisible_(True)
        self.window.setAlphaValue_(alphaValue)

    def dayOver(self):
        """
        The day is over, so there will be no more intervals.
        """
        self.active = False
        print("The day is over. Goodbye.")
        self.window.setIsVisible_(False)


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


def expressIntention(day: Day, newIntention: str) -> None:
    """
    Express the given intention to the given day.
    """
    intentionResult = day.expressIntention(rawSeconds(), newIntention)
    print("IR", intentionResult)
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
        print("very surprised:", intentionResult)
    print("saving day")
    saveDay(day)
    print("saved")


def setIntention(day: Day) -> None:
    try:
        newIntention = getString(
            title="Set An Intention",
            question="What is your intention?",
            defaultValue="",
        )
        print("String Get")
        expressIntention(day, newIntention)
    except BaseException:
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
        print("Creating testing day")
        return Day.forTesting()
    else:
        print("New production-mode date", forDate)
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
    def initWithMenu_(self, menu):
        """ """
        self.menu = menu
        return self

    def performKeyEquivalent_(self, event):
        """ """
        print("pek", event)
        handled = self.menu.performKeyEquivalent_(event)
        if handled:
            print("HANDLED")

    def keyDown_(self, event):
        handled = self.menu.performKeyEquivalent_(event)
        if handled:
            return
        super().keyDown_(event)
        print("made it out alive")


@dataclass
class DayManager(object):
    observer: MacPomObserver
    window: HUDWindow
    progress: BigProgressView
    reactor: IReactorTCP
    editController: DayEditorController
    day: Day = field(default_factory=lambda: newDay(date.today()))
    screenReconfigurationTimer: Optional[DelayedCall] = None
    profile: Optional[Profile] = None

    @classmethod
    def new(cls, reactor, editController) -> DayManager:
        progressView = BigProgressView.alloc().init()
        window = makeOneWindow(progressView)
        observer = MacPomObserver(progressView, window)
        return cls(
            observer,
            window,
            progressView,
            reactor,
            editController,
        )

    def screensChanged(self) -> None:
        print("screens changed...")

        def recreateWindow():
            print("recreating window")
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
        print("stats?")
        import os

        profile.dump_stats(os.path.expanduser("~/pom.pstats"))
        print("stats.")

    def start(self) -> None:
        status = Status(can)

        def doList():
            self.editController.editorWindow.setIsVisible_(True)
            NSApp().activateIgnoringOtherApps_(True)

        def raiseException():
            # from Foundation import NSException
            # NSException.raise_format_("SampleException", "a thing happened")
            print("raising...")
            raise Exception("report this pls")

        status.menu(
            [
                ("Intention", lambda: setIntention(self.day)),
                (
                    "Bonus Pomodoro",
                    lambda: bonus(localDate(rawSeconds()), self.day),
                ),
                ("Evaluate", lambda: self.setSuccess()),
                ("Start Profiling", lambda: self.startProfiling()),
                ("Finish Profiling", lambda: self.stopProfiling()),
                ("List Pomodoros", doList),
                ("Break", raiseException),
                ("Quit", quit),
            ]
        )

        self.editController.editorWindow.setNextResponder_(
            MenuForwarder.alloc().initWithMenu_(status.item.menu()).retain()
        )

        def update() -> None:
            try:
                try:
                    currentTimestamp = rawSeconds()
                    # presentDate = localDate(currentTimestamp).date()
                    presentDate = date.today()
                    if presentDate != self.day.startTime.date():
                        self.day = newDay(presentDate)
                    self.day.advanceToTime(currentTimestamp, self.observer)
                    status.item.setTitle_(labelForDay(self.day))
                    finishTime = rawSeconds()
                except BaseException:
                    print(Failure().getTraceback())
            finally:
                # trying to stick to 1% CPU...
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

    def initWithDay_(self, day: Day) -> DescriptionChanger:
        self.day = day
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
        print("chagne", ofObject, change)
        if change.get("notificationIsPrior"):
            print("ignoring prior")
            return
        if self.observing:
            print("ignoring observing", ofObject, change, context)
            return
        with self.ignoreChanges():
            print("ACTING")
            assert keyPath == "description"
            pom: Pomodoro = ofObject["pom"]
            newDescription: str = change["new"]
            result = self.day.expressIntention(
                rawSeconds(), newDescription, pom
            )
            if result != IntentionResponse.WasSet:
                print("WAS NOT SET, REVERSING")
                reverseValue = change["old"]
                from PyObjCTools.AppHelper import callLater

                def later():
                    print("DEFERRED CHANGE")
                    with self.ignoreChanges():
                        ofObject["description"] = reverseValue
                    print("CHANG")

                callLater(0.0, later)
                print("REVERSED?", repr(ofObject["description"]))
                return
            print("changed description, saving", repr(newDescription))
            saveDay(self.day)
            print("saved.")


class DayEditorController(NSObject):
    arrayController = IBOutlet()
    editorWindow = IBOutlet()
    tableView = IBOutlet()

    @IBAction
    def hideMe_(self, sender) -> None:
        self.editorWindow.setIsVisible_(False)


@mainpoint()
def main(reactor: IReactorTCP) -> None:
    import traceback, sys

    ctrl = DayEditorController.new()
    stuff = list(
        NSNib.alloc()
        .initWithNibNamed_bundle_("GoalListWindow.nib", None)
        .instantiateWithOwner_topLevelObjects_(ctrl, None)
    )
    setupNotifications()
    withdrawIntentPrompt()
    dayManager = DayManager.new(reactor, ctrl)
    observer = DescriptionChanger.alloc().initWithDay_(dayManager.day).retain()
    with observer.ignoreChanges():
        for i, pomOrBreak in enumerate(
            dayManager.day.elapsedIntervals + dayManager.day.pendingIntervals
        ):
            if isinstance(pomOrBreak, Pomodoro):
                # todo: bind editability to one of these attributes so we can
                # control it on a per-row basis
                rowDict = NSMutableDictionary.dictionaryWithDictionary_(
                    {
                        "index": str(i),
                        "startTime": pomOrBreak.startTime.isoformat(),
                        "endTime": pomOrBreak.startTime.isoformat(),
                        "description": pomOrBreak.intention.description or ""
                        if pomOrBreak.intention is not None
                        else "",
                        "success": str(pomOrBreak.intention.wasSuccessful)
                        if pomOrBreak.intention is not None
                        else "Failed"
                        if rawSeconds() > pomOrBreak.endTimestamp
                        else "Not Started",
                        "pom": pomOrBreak,
                    }
                )
                ctrl.arrayController.addObject_(rowDict)
                rowDict.addObserver_forKeyPath_options_context_(
                    observer, "description", 0xF, 0x020202
                )
    ctrl.tableView.reloadData()
    dayManager.start()
    callOnNotification(
        NSApplicationDidChangeScreenParametersNotification,
        dayManager.screensChanged,
    )
