# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from cProfile import Profile
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import (
    Any,
    Callable,
    ClassVar,
    Dict,
    Iterable,
    Iterator,
    List,
    NoReturn,
    Optional,
    Tuple,
)

from twisted.internet.base import DelayedCall
from twisted.internet.interfaces import IDelayedCall, IReactorTime
from twisted.internet.task import LoopingCall
from twisted.python.failure import Failure

import math
from ..pommodel import (
    Break,
    Day,
    Intention,
    IntentionResponse,
    IntentionSuccess,
    Interval,
    Pomodoro,
)
from ..storage import DayLoader, TEST_MODE
from .mac_utils import callOnNotification, datetimeFromNSDate, localDate
from .notifs import (
    askForIntent,
    notify,
    setupNotifications,
    withdrawIntentPrompt,
)
from .quickapp import Status, mainpoint, quit
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
)

from Foundation import NSIndexSet, NSLog, NSMutableDictionary, NSObject, NSRect

from PyObjCTools.AppHelper import callLater
from dateutil.tz import tzlocal
from dateutil.relativedelta import relativedelta
from objc import IBAction, IBOutlet


# fillRect = NSBezierPath.fillRect_
fillRect = NSRectFill


def _removeWindows(self: ProgressController) -> None:
    """
    Remove the progress views from the given ProgressController.
    """
    self.progressViews = []
    self.hudWindows, oldHudWindows = [], self.hudWindows
    for eachWindow in oldHudWindows:
        eachWindow.close()
        eachWindow.setContentView_(None)

@dataclass
class ProgressController(object):
    """
    Coordinating object that maintains a set of BigProgressViews on each display.
    """

    percentage: float = 0.0
    leftColor: NSColor = NSColor.greenColor()
    rightColor: NSColor = NSColor.redColor()
    progressViews: List[BigProgressView] = field(default_factory=list)
    hudWindows: List[HUDWindow] = field(default_factory=list)
    alphaValue: float = 0.1
    shouldBeVisible: bool = False

    def setPercentage(self, percentage: float) -> None:
        """
        set the percentage complete
        """
        self.percentage = percentage
        for eachView in self.progressViews:
            eachView.setPercentage_(percentage)

    def setColors(self, left: NSColor, right: NSColor) -> None:
        """
        set the left and right colors
        """
        self.leftColor = left
        self.rightColor = right
        for eachView in self.progressViews:
            eachView.setLeftColor_(left)
            eachView.setRightColor_(right)

    def show(self) -> None:
        """
        Display this progress controller on all displays
        """
        self.shouldBeVisible = True
        if not self.progressViews:
            self.redisplay()

    def redisplay(self) -> None:
        if self.shouldBeVisible:
            _removeWindows(self)
            for eachScreen in NSScreen.screens():
                (win := hudWindowOn(eachScreen)).setContentView_(
                    newProgressView := BigProgressView.alloc().init()
                )
                win.setAlphaValue_(self.alphaValue)
                newProgressView.setLeftColor_(self.leftColor)
                newProgressView.setRightColor_(self.rightColor)
                newProgressView.setPercentage_(self.percentage)
                self.hudWindows.append(win)
                self.progressViews.append(newProgressView)

    def hide(self) -> None:
        self.shouldBeVisible = False
        _removeWindows(self)

    def setAlpha(self, alphaValue: float) -> None:
        self.alphaValue = alphaValue
        for eachWindow in self.hudWindows:
            eachWindow.setAlphaValue_(alphaValue)


def hudWindowOn(screen: NSScreen) -> HUDWindow:
    app = NSApp()
    frame = screen.frame()
    height = 50
    hpadding = frame.size.width // 10
    vpadding = frame.size.height // (4 if TEST_MODE else 3)
    contentRect = NSRect(
        (hpadding + frame.origin[0], vpadding + frame.origin[1]),
        (frame.size.width - (hpadding * 2), height),
    )
    styleMask = NSBorderlessWindowMask
    backing = NSBackingStoreBuffered
    defer = False
    win = HUDWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        contentRect,
        styleMask,
        backing,
        defer,
    )
    # Let python handle the refcounting thanks
    win.setReleasedWhenClosed_(False)
    win.setCollectionBehavior_(
        NSWindowCollectionBehaviorCanJoinAllSpaces
        | NSWindowCollectionBehaviorStationary
    )
    win.setIgnoresMouseEvents_(True)
    win.setBackgroundColor_(NSColor.blackColor())
    win.setLevel_(NSFloatingWindowLevel)
    win.orderFront_(app)
    return win


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

    def percentage(self) -> float:
        return self._percentage

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
        f"Your intention was: ???{intention.description}???.  How did you track to it?"
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


responses: Dict[IntentionResponse, intcb] = {}


def _intention(
    response: IntentionResponse,
    responses: Dict[IntentionResponse, intcb] = responses,
) -> Callable[[intcb], intcb]:
    def decorator(f: intcb) -> intcb:
        responses[response] = f
        return f

    return decorator


@dataclass
class MacPomObserver(object):
    """
    Binding of model notifications interface to mac GUI
    """

    progressController: ProgressController
    refreshList: Callable[[], None]
    clock: IReactorTime
    dayLoader: DayLoader
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
    alphaVariance: float = 0.3
    pulseMultiplier: float = 1.5
    pulseTime: float = 1.0
    progressAnimation: Optional[LoopingCall] = None

    def __post_init__(self) -> None:
        if self.active:
            self.progressController.show()
        else:
            self.progressController.hide()

    def breakStarting(self, startingBreak: Break) -> None:
        """
        A break is starting.
        """
        self.active = True
        self.progressController.show()
        notify("Starting Break", "Take it easy for a while.")
        self.refreshList()

    def pomodoroStarting(self, day: Day, startingPomodoro: Pomodoro) -> None:
        """
        A pomodoro is starting; time to express an intention.
        """
        self.active = True
        self.lastThreshold = 0.0
        self.progressController.show()
        if (
            startingPomodoro.intention is None
            or startingPomodoro.intention.description is None
        ):

            def doExpressIntention(userText: str) -> None:
                expressIntention(self.clock, day, userText, self.dayLoader)
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

    @_intention(IntentionResponse.CanBeSet)
    def _canBeSet(self, interval: Interval, percentageElapsed: float) -> None:
        self.baseAlphaValue = MacPomObserver.baseAlphaValue + 0.1
        self.alphaVariance = MacPomObserver.alphaVariance * 2
        self.pulseMultiplier = MacPomObserver.pulseMultiplier * 2

        self.progressController.setColors(
            NSColor.yellowColor(), NSColor.purpleColor()
        )
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

        self.progressController.setColors(
            NSColor.greenColor(), NSColor.blueColor()
        )
        if isinstance(interval, Pomodoro) and interval.intention is not None:
            # TODO: maybe put reminder messages in the model?
            for pct, message in self.thresholds:
                if self.lastThreshold <= pct and percentageElapsed > pct:
                    self.lastThreshold = percentageElapsed
                    notify(
                        "Remember Your Intention",
                        message,
                        "???" + interval.intention.description + "???",
                    )

    @_intention(IntentionResponse.OnBreak)
    def _onBreak(self, interval: Interval, percentageElapsed: float) -> None:
        # Neutral "take it easy" colors for breaks
        self.baseAlphaValue = MacPomObserver.baseAlphaValue
        self.pulseMultiplier = MacPomObserver.pulseMultiplier / 2
        self.alphaVariance = MacPomObserver.alphaVariance / 2

        self.progressController.setColors(
            NSColor.lightGrayColor(), NSColor.darkGrayColor()
        )

    @_intention(IntentionResponse.TooLate)
    def _tooLate(self, interval: Interval, percentageElapsed: float) -> None:
        self.baseAlphaValue = MacPomObserver.baseAlphaValue
        self.pulseMultiplier = MacPomObserver.pulseMultiplier
        self.alphaVariance = MacPomObserver.alphaVariance

        # Angry "You forgot" colors for setting it too late
        self.progressController.setColors(
            NSColor.orangeColor(), NSColor.redColor()
        )

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
            responses[canSetIntention](self, interval, percentageElapsed)
            self.refreshList()

        previousPercentageElapsed = self.progressController.percentage
        if percentageElapsed < previousPercentageElapsed:
            previousPercentageElapsed = 0
        elapsedDelta = percentageElapsed - previousPercentageElapsed
        startTime = self.clock.seconds()

        def updateSome() -> None:
            now = self.clock.seconds()
            percentDone = (now - startTime) / self.pulseTime
            easedEven = math.sin((percentDone * math.pi))
            easedUp = math.sin((percentDone * math.pi) / 2.0)
            self.progressController.setPercentage(
                previousPercentageElapsed + (easedUp * elapsedDelta)
            )
            if percentDone >= 1.0:
                alphaValue = self.baseAlphaValue
                self.progressAnimation = None
                lc.stop()
            else:
                alphaValue = (
                    easedEven * self.alphaVariance
                ) + self.baseAlphaValue
            self.progressController.setAlpha(alphaValue)

        if self.progressAnimation is not None:
            self.progressAnimation.stop()
        self.progressAnimation = lc = LoopingCall(updateSome)
        lc.start(1.0 / 60.0)
        self.active = True
        self.progressController.show()

    def dayOver(self) -> None:
        """
        The day is over, so there will be no more intervals.
        """
        self.active = False
        self.progressController.hide()
        self.refreshList()


def expressIntention(
    clock: IReactorTime, day: Day, newIntention: str, dayLoader: DayLoader
) -> None:
    """
    Express the given intention to the given day.
    """
    intentionResult = day.expressIntention(clock.seconds(), newIntention)
    if intentionResult == IntentionResponse.WasSet:
        notify("Intention Set", f"???{newIntention}???")
    elif intentionResult == IntentionResponse.AlreadySet:
        description = day.pendingIntervals[
            0
        ].intention.description  # type: ignore
        notify(
            "Intention Not Set",
            "Already Specified",
            informativeText=f"intention was already: ???{description}???",
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
    dayLoader.saveDay(day)


def setIntention(clock: IReactorTime, day: Day, dayLoader: DayLoader) -> None:
    try:
        newIntention = getString(
            title="Set An Intention",
            question="What is your intention?",
            defaultValue="",
        )
        expressIntention(clock, day, newIntention, dayLoader)
    except BaseException:
        # TODO: roll up error reporting into common event-handler
        print(Failure().getTraceback())


def bonus(when: datetime, day: Day, dayLoader: DayLoader) -> None:
    """
    Start a new pom outside the usual bounds of pomodoro time, either before or
    after the end of the day.
    """
    try:
        day.bonusPomodoro(when)
        dayLoader.saveDay(day)
    except BaseException:
        # TODO: roll up error reporting into common event-handler
        print(Failure().getTraceback())


def nowNative() -> datetime:
    return datetime.now(tz=tzlocal())


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
    remaining, e = (score.remaining, "???") if score.remaining else ("", "")
    return (
        f"{icon}: {score.hits}??? {score.misses}??? {unevaluated}{q}{remaining}{e}"
    )


can = "????"
tomato = "????"


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
    progressController: ProgressController
    reactor: IReactorTime
    editController: DayEditorController
    dayLoader: DayLoader
    day: Day
    profile: Optional[Profile] = None
    updateDelayedCall: Optional[IDelayedCall] = None
    status: Optional[Status] = None

    @classmethod
    def new(
        cls,
        reactor: IReactorTime,
        editController: DayEditorController,
        dayLoader: DayLoader,
    ) -> DayManager:

        progressController = ProgressController()

        def listRefresher() -> None:
            reactor.callLater(0, self.update)
            if editController.editorWindow.isVisible():
                editController.refreshStatus_(self.day)

        self = cls(
            MacPomObserver(
                progressController, listRefresher, reactor, dayLoader
            ),
            progressController,
            reactor,
            editController,
            dayLoader,
            dayLoader.loadOrCreateDay(date.fromtimestamp(reactor.seconds())),
        )
        return self

    def screensChanged(self) -> None:
        self.progressController.redisplay()

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
        bonus(localDate(self.reactor.seconds()), self.day, self.dayLoader)
        self.observer.refreshList()

    def doSetIntention(self) -> None:
        setIntention(self.reactor, self.day, self.dayLoader)
        self.observer.refreshList()

    def start(self) -> None:
        status = self.status = Status(can)

        def doList() -> None:
            self.editController.editorWindow.setIsVisible_(True)
            self.editController.refreshStatus_(self.day)
            NSApp().activateIgnoringOtherApps_(True)

        def raiseException() -> NoReturn:
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
                ("Reposition Window", lambda: self.screensChanged()),
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

        self.update()

    def update(self) -> None:
        pulseRate = 10.0
        currentTimestamp = self.reactor.seconds()
        presentDate = date.today()
        if self.updateDelayedCall is not None:
            self.updateDelayedCall.cancel()
            self.updateDelayedCall = None
        intervalBeforeAdvancing = None
        try:
            intervalBeforeAdvancing = self.day.currentOrNextInterval()
            # presentDate = localDate(currentTimestamp).date()
            if presentDate != self.day.startTime.date():
                self.day = self.dayLoader.loadOrCreateDay(presentDate)
            self.day.advanceToTime(currentTimestamp, self.observer)
            label = labelForDay(self.day)
            if TEST_MODE:
                label = "????" + label
            if (status := self.status) is not None:
                status.item.setTitle_(label)
        except BaseException:
            print(Failure().getTraceback())

        try:
            currentInterval = self.day.currentOrNextInterval()
            howLong = (
                (
                    (
                        self.day.startTime
                        + relativedelta(hour=0, minute=0, second=1, days=1)
                    ).timestamp()
                    - currentTimestamp
                    # Make sure that we always schedule one more update past
                    # the end of the day so that the progress bar properly
                    # disappears.
                    if intervalBeforeAdvancing is None
                    else 1.0
                )
                if currentInterval is None
                else (
                    pulseRate
                    - (
                        (currentTimestamp - currentInterval.startTimestamp)
                        % pulseRate
                    )
                    if currentTimestamp > currentInterval.startTimestamp
                    else currentInterval.startTimestamp - currentTimestamp
                )
            )

            def nextUpdate() -> None:
                self.updateDelayedCall = None
                self.update()

            self.updateDelayedCall = self.reactor.callLater(
                howLong, nextUpdate
            )
        except BaseException:
            print(Failure().getTraceback())

    def setSuccess(self) -> None:
        pomsToEvaluate = self.day.unEvaluatedPomodoros()
        if not pomsToEvaluate:
            notify(
                "No Evaluations Pending",
                informativeText="You've already evaluated everything you can.",
            )
            return
        aPom = pomsToEvaluate[0]
        # todo: teach mypy about this
        assert (
            aPom.intention is not None
        ), "unEvaluatedPomodoros scans this already"
        succeeded = getSuccess(aPom.intention)
        self.day.evaluateIntention(aPom, succeeded)
        self.dayLoader.saveDay(self.day)
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


class DescriptionChanger(NSObject):
    observing = False

    def initWithDay_clock_andController_(
        self, day: Day, clock: IReactorTime, ctrl: DayEditorController
    ) -> DescriptionChanger:
        self.day = day
        self.clock = clock
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
                self.clock.seconds(), newDescription, pom
            )
            callLater(0.0, lambda: self.ctrl.refreshStatus_(self.day))
            self.ctrl.dayLoader.saveDay(self.day)


def poms2Dicts(
    day: Day, now: float, poms: Iterable[Pomodoro]
) -> Iterable[Dict[str, object]]:
    """
    Convert a set of pomodoros to pretty-printed dictionaries for display with
    respect to a given POSIX epoch timestamp.
    """
    # TODO: would this be useful for other frontends? Is it really
    # mac-specific?
    hasCurrent = False
    for i, pomOrBreak in enumerate(poms, start=1):
        # todo: bind editability to one of these attributes so we can
        # control it on a per-row basis
        desc = (
            pomOrBreak.intention.description or ""
            if pomOrBreak.intention is not None
            else ""
        )
        canChange = (now < pomOrBreak.startTimestamp) or (
            (pomOrBreak.intention is None)
            and (now < (pomOrBreak.startTimestamp + day.intentionGracePeriod))
        )
        if not canChange:
            desc = "???? " + desc

        isCurrent = False
        if not hasCurrent:
            if now < pomOrBreak.endTimestamp:
                hasCurrent = isCurrent = True

        yield {
            "index": f"{i}{'???' if isCurrent else ''}",
            "startTime": pomOrBreak.startTime.time().isoformat(
                timespec="minutes"
            ),
            "endTime": pomOrBreak.endTime.time().isoformat(timespec="minutes"),
            "description": desc,
            "success": ("???" if now > pomOrBreak.endTimestamp else "???")
            if pomOrBreak.intention is None
            else {
                None: "???" if now < pomOrBreak.startTimestamp else "????",
                IntentionSuccess.Achieved: "???",
                IntentionSuccess.Focused: "????",
                IntentionSuccess.Distracted: "????",
                IntentionSuccess.NeverEvaluated: "????",
                True: "???",
                False: "????",
            }[pomOrBreak.intention.wasSuccessful],
            "pom": pomOrBreak,
        }


class DayEditorController(NSObject):
    arrayController = IBOutlet()
    editorWindow = IBOutlet()
    tableView = IBOutlet()
    datePickerCell: Optional[NSCell] = IBOutlet()
    dayLabelField: Optional[NSTextFieldCell] = IBOutlet()
    observer = None
    clock: IReactorTime
    dayLoader: DayLoader

    def initWithClock_andDayLoader_(
        self, clock: IReactorTime, dayLoader: DayLoader
    ) -> DayEditorController:
        self.clock = clock
        self.dayLoader = dayLoader
        return self

    @IBAction
    def hideMe_(self, sender) -> None:
        self.editorWindow.setIsVisible_(False)

    @IBAction
    def dateWasSet_(self, sender: object) -> None:
        """
        The date was set to a new value.
        """
        assert (
            self.datePickerCell is not None
        ), "The date picker cell should be set by nib loading."
        dateValue = self.datePickerCell.dateValue()
        self.refreshStatus_(
            self.dayLoader.loadOrCreateDay(
                datetimeFromNSDate(dateValue).date()
            )
        )

    def refreshStatus_(self, day: Day) -> None:
        previouslySelectedRow = self.tableView.selectedRow()
        assert self.dayLabelField is not None, "should be set by nib loading"
        self.dayLabelField.setObjectValue_(labelForDay(day))
        oldObserver = self.observer
        if oldObserver is not None:
            for eachPreviousDict in self.arrayController.arrangedObjects():
                eachPreviousDict.removeObserver_forKeyPath_(
                    oldObserver, "description"
                )
        observer = (
            self.observer
        ) = DescriptionChanger.alloc().initWithDay_clock_andController_(
            day, self.clock, self
        )
        now = self.clock.seconds()
        onlyPoms = [
            each
            for each in day.elapsedIntervals + day.pendingIntervals
            if isinstance(each, Pomodoro)
        ]
        with observer.ignoreChanges():
            self.arrayController.removeObjects_(
                list(self.arrayController.arrangedObjects())
            )
            for pomAsDict in poms2Dicts(day, now, onlyPoms):
                rowDict = NSMutableDictionary.dictionaryWithDictionary_(
                    pomAsDict
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

    dayLoader = DayLoader()
    ctrl = DayEditorController.alloc().initWithClock_andDayLoader_(
        reactor, dayLoader
    )
    stuff = list(
        NSNib.alloc()
        .initWithNibNamed_bundle_("GoalListWindow.nib", None)
        .instantiateWithOwner_topLevelObjects_(ctrl, None)
    )
    setupNotifications()
    withdrawIntentPrompt()
    dayManager = DayManager.new(reactor, ctrl, dayLoader)
    dayManager.start()
    callOnNotification(
        NSApplicationDidChangeScreenParametersNotification,
        dayManager.screensChanged,
    )
