from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, TYPE_CHECKING
from math import sqrt, cos, sin

from Foundation import NSRect, NSPoint
from AppKit import (
    NSAttributedString,
    NSFontAttributeName,
    NSFont,
    NSForegroundColorAttributeName,
    NSStrokeColorAttributeName,
)

from twisted.internet.defer import Deferred
from twisted.internet.interfaces import IReactorTime
from twisted.internet.task import LoopingCall
from twisted.logger import Logger
from twisted.python.failure import Failure

from .mac_utils import showFailures


log = Logger()

import math
from ..storage import TEST_MODE

from objc import super

from AppKit import (
    NSApp,
    NSBackingStoreBuffered,
    NSBezierPath,
    NSBorderlessWindowMask,
    NSColor,
    NSCompositingOperationCopy,
    NSEvent,
    NSFloatingWindowLevel,
    NSFocusRingTypeNone,
    NSRectFillListWithColorsUsingOperation,
    NSScreen,
    NSView,
    NSWindow,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorStationary,
    NSMakePoint,
    NSStrokeWidthAttributeName,
)

# https://github.com/ronaldoussoren/pyobjc/issues/540
NSWindowCollectionBehaviorCanJoinAllApplications = 1 << 18
NSWindowCollectionBehaviorAuxiliary = 1 << 17


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


class AbstractProgressView(NSView):
    """
    Base boilerplate for a view that can draw progress.
    """

    _reticleText: str = ""
    _percentage: float = 0.0
    _leftColor = NSColor.greenColor()
    _rightColor = NSColor.redColor()

    _alphaValue: float = 1 / 4

    if TYPE_CHECKING:

        @classmethod
        def alloc(cls) -> AbstractProgressView:
            return cls()

        def init(self) -> AbstractProgressView:
            return self

    # first-party objc methods

    def configureWindow_(self, win: HUDWindow) -> None:
        win.setContentView_(self)
        win.setOpaque_(False)
        win.setBackgroundColor_(NSColor.clearColor())

    def changeAlphaValue_forWindow_(
        self, newAlphaValue: float, win: NSWindow
    ) -> None:
        self._alphaValue = newAlphaValue
        self.setNeedsDisplay_(True)

    def setReticleText_(self, newText: str) -> None:
        """
        Set the text that should be displayed at the center of the user's
        screen.
        """
        self._reticleText = newText

    def setPercentage_(self, newPercentage: float) -> None:
        """
        Set the percentage-full here.
        """
        self._percentage = newPercentage
        self.setNeedsDisplay_(True)

    def setLeftColor_(self, newLeftColor: NSColor) -> None:
        self._leftColor = newLeftColor
        # self.setNeedsDisplay_(True)

    def setRightColor_(self, newRightColor: NSColor) -> None:
        self._rightColor = newRightColor
        # self.setNeedsDisplay_(True)

    # NSView Boilerplate
    def isOpaque(self) -> bool:
        return False

    @classmethod
    def defaultFocusRingType(cls) -> int:
        return NSFocusRingTypeNone  # type: ignore

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


def fullScreenSizer(
    screen: NSScreen, hpadding: int = 50, vpadding: int = 50
) -> NSRect:
    """
    Return a rectangle that is inset from the full screen with some padding.
    """
    frame = screen.visibleFrame()
    return NSRect(
        (frame.origin[0] + hpadding, frame.origin[1] + vpadding),
        (
            frame.size.width - (hpadding * 2),
            frame.size.height - (vpadding * 2),
        ),
    )


def midScreenSizer(screen: NSScreen) -> NSRect:
    height = 50
    frame = screen.visibleFrame()
    hpadding = frame.size.width // 10
    vpadding = frame.size.height // (4 if TEST_MODE else 3)
    return NSRect(
        (hpadding + frame.origin[0], vpadding + frame.origin[1]),
        (frame.size.width - (hpadding * 2), height),
    )


def hudWindowOn(
    screen: NSScreen,
    sizer: Callable[[NSScreen], NSRect],
    styleMask=NSBorderlessWindowMask,
) -> HUDWindow:
    app = NSApp()
    backing = NSBackingStoreBuffered
    defer = False
    contentRect = sizer(screen)
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
        | NSWindowCollectionBehaviorAuxiliary
    )
    win.setIgnoresMouseEvents_(True)
    win.setLevel_(NSFloatingWindowLevel)
    win.orderFront_(app)
    return win  # type: ignore


DEFAULT_BASE_ALPHA = 0.15

ProgressViewFactory = Callable[[], AbstractProgressView]


@dataclass
class ProgressController(object):
    """
    Coordinating object that maintains a set of BigProgressViews on each display.
    """

    percentage: float = 0.0
    leftColor: NSColor = NSColor.greenColor()
    rightColor: NSColor = NSColor.redColor()
    progressViewFactory: ProgressViewFactory = lambda: PieTimer.alloc().init()
    windowSizer: Callable[[NSScreen], NSRect] = fullScreenSizer
    progressViews: List[AbstractProgressView] = field(default_factory=list)
    hudWindows: List[HUDWindow] = field(default_factory=list)
    alphaValue: float = 0.1
    shouldBeVisible: bool = False
    _animationInProgress: Deferred[None] | None = None
    reticleText: str = ""

    def animatePercentage(
        self,
        clock: IReactorTime,
        percentageElapsed: float,
        pulseTime: float = 1.0,
        baseAlphaValue: float = DEFAULT_BASE_ALPHA,
        alphaVariance: float = 0.3,
    ) -> Deferred[None]:
        """
        Animate a percentage increase.
        """
        if self._animationInProgress is not None:
            return self._animationInProgress.addCallback(
                lambda ignored: self.animatePercentage(
                    clock,
                    percentageElapsed,
                    pulseTime,
                    baseAlphaValue,
                    alphaVariance,
                )
            )
        startTime = clock.seconds()
        previousPercentageElapsed = self.percentage
        if percentageElapsed < previousPercentageElapsed:
            previousPercentageElapsed = 0
        elapsedDelta = percentageElapsed - previousPercentageElapsed

        def updateSome() -> None:
            now = clock.seconds()
            percentDone = (now - startTime) / pulseTime
            easedEven = math.sin((percentDone * math.pi))
            easedUp = math.sin((percentDone * math.pi) / 2.0)
            self.setPercentage(
                previousPercentageElapsed + (easedUp * elapsedDelta)
            )
            if percentDone >= 1.0:
                alphaValue = baseAlphaValue
                lc.stop()
            else:
                alphaValue = (easedEven * alphaVariance) + baseAlphaValue
            self.setAlpha(alphaValue)

        lc = LoopingCall(updateSome)

        def clear(ignored: object) -> None:
            self._animationInProgress = None
            if isinstance(ignored, Failure):
                log.failure("while animating", ignored)

        self._animationInProgress = lc.start(1.0 / 30.0).addCallback(clear)
        self.show()
        return self._animationInProgress

    def setPercentage(self, percentage: float) -> None:
        """
        set the percentage complete
        """
        self.percentage = percentage
        for eachView in self.progressViews:
            eachView.setPercentage_(percentage)

    def setReticleText(self, newText: str) -> None:
        """
        Set the reticle text.
        """
        self.reticleText = newText
        for eachView in self.progressViews:
            eachView.setReticleText_(newText)

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
                newProgressView = self.progressViewFactory()
                win = hudWindowOn(eachScreen, self.windowSizer)
                newProgressView.configureWindow_(win)
                newProgressView.changeAlphaValue_forWindow_(
                    self.alphaValue, win
                )
                newProgressView.setLeftColor_(self.leftColor)
                newProgressView.setRightColor_(self.rightColor)
                newProgressView.setPercentage_(self.percentage)
                newProgressView.setReticleText_(self.reticleText)
                self.hudWindows.append(win)
                self.progressViews.append(newProgressView)

    def hide(self) -> None:
        self.shouldBeVisible = False
        _removeWindows(self)

    def setAlpha(self, alphaValue: float) -> None:
        self.alphaValue = alphaValue
        for eachWindow, eachView in zip(self.hudWindows, self.progressViews):
            eachView.changeAlphaValue_forWindow_(alphaValue, eachWindow)


class FlatProgressBar(AbstractProgressView):
    """
    An L{AbstractProgressView} that draws itself as a big bar.
    """

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

    # NSView Boilerplate
    def isOpaque(self) -> bool:
        """
        This view is opaque since it draws on the full window, try to be faster
        compositing it.
        """
        return True


def move(start: NSPoint, towards: NSPoint, distance: float) -> NSPoint:
    """
    Return the L{Point} that's the result of moving C{distance} from C{start}
    along the line towards C{towards}.
    """
    a = towards.x - start.x
    b = towards.y - start.y
    c = sqrt((a**2) + (b**2))

    return NSMakePoint(
        start.x + (a * (distance / c)),
        start.y + (b * (distance / c)),
    )


def edge(start: NSPoint, radius: float, theta: float) -> NSPoint:
    """
    Return the point on the edge of the circle.
    """
    return NSMakePoint(
        start.x + radius * cos(theta),
        y=start.y + radius * sin(theta),
    )


class PieTimer(AbstractProgressView):
    """
    A timer that draws itself as two large arcs.
    """

    def drawRect_(self, rect: NSRect) -> None:
        """
        draw the arc (ignore the given rect, draw to bounds)
        """
        with showFailures():
            super().drawRect_(rect)
            bounds = self.bounds()
            w, h = bounds.size.width / 2, bounds.size.height / 2
            center = NSMakePoint(w, h)

            radius = min([w, h]) * 0.95

            if TEST_MODE:
                radius *= 0.7

            def doArc(start: float, end: float) -> NSBezierPath:
                thickness = 0.1
                innerRadius = radius * (1 - thickness)

                # outerStart = edge(center, radius, start)
                # innerStart = edge(center, innerRadius, start)
                # outerEnd = edge(center, radius, end)
                # innerEnd = edge(center, innerRadius, end)

                aPath = NSBezierPath.bezierPath()
                # aPath.appendBezierPathWithPoints_count_([innerStart], 1)
                aPath.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_(
                    center, radius, start, end
                )
                # already at outerEnd
                # aPath.appendBezierPathWithPoints_count_([innerEnd], 1)
                aPath.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_clockwise_(
                    center, radius * (1 - thickness), end, start, True
                )
                # aPath.setLineWidth_(5)
                return aPath

            startDegrees = ((360 * self._percentage) + 90) % 360
            endDegrees = 90
            arc1 = doArc(startDegrees, endDegrees)
            arc2 = doArc(endDegrees, startDegrees)
            leftWithAlpha = self._leftColor.colorWithAlphaComponent_(
                self._alphaValue
            )
            leftWithAlpha.setFill()
            arc1.fill()
            self._rightColor.colorWithAlphaComponent_(
                self._alphaValue
            ).setFill()
            arc2.fill()
            lineAlpha = (self._alphaValue - DEFAULT_BASE_ALPHA) * 4
            if lineAlpha > 0:
                whiteWithAlpha = NSColor.whiteColor().colorWithAlphaComponent_(
                    lineAlpha
                )
                if self._reticleText:
                    font = NSFont.systemFontOfSize_(
                        36.0
                    )  # NSFont.fontWithName_size_("System", 36.0)
                    aString = (
                        NSAttributedString.alloc().initWithString_attributes_(
                            self._reticleText,
                            {
                                NSForegroundColorAttributeName: leftWithAlpha,
                                NSFontAttributeName: font,
                                NSStrokeColorAttributeName: whiteWithAlpha,
                                # negative widths are percentages of font point size
                                NSStrokeWidthAttributeName: -2.0,
                            },
                        )
                    )
                    textSize = aString.size()
                    aString.drawAtPoint_(
                        NSMakePoint(
                            center.x - (textSize.width / 2),
                            center.y - (textSize.height / 2),
                        )
                    )
                whiteWithAlpha.setStroke()
                arc1.setLineWidth_(1 / 4)
                arc2.setLineWidth_(1 / 4)
                arc1.stroke()
                arc2.stroke()


def _removeWindows(self: ProgressController) -> None:
    """
    Remove the progress views from the given ProgressController.
    """
    self.progressViews = []
    self.hudWindows, oldHudWindows = [], self.hudWindows
    for eachWindow in oldHudWindows:
        eachWindow.close()
        eachWindow.setContentView_(None)
