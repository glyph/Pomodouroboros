from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from Foundation import NSIndexSet, NSLog, NSMutableDictionary, NSObject, NSRect
from twisted.internet.defer import Deferred
from twisted.internet.interfaces import IReactorTime
from twisted.internet.task import LoopingCall
from twisted.python.failure import Failure
from twisted.logger import Logger

log = Logger()

import math
from ..storage import TEST_MODE
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
    NSMakePoint,
)


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




class BigArcView(NSView):
    """
    draw an arc the size of this view
    """

    percentage: float = 70.0

    def awakeFromNib(self) -> None:
        """
        debug animation to test arc drawing
        """
        print("init")
        super().init()
        print("super init")
        self.percentage = 65.0
        def bump():
            self.percentage += (1/120)
            self.percentage %= 100.0
            self.setNeedsDisplay_(True)
            # self.window().setNeedsDisplay_(True)
        lc = LoopingCall(bump)
        lc.start(1/120)

    def drawRect_(self, rect: NSRect) -> None:
        """
        draw the arc (ignore the given rect, draw to bounds)
        """
        bounds = self.bounds()
        w, h = bounds.size.width / 2, bounds.size.height / 2
        center = NSMakePoint(w, h)
        aPath = NSBezierPath.bezierPath()
        radius = min([w, h]) * 0.85
        aPath.appendBezierPathWithPoints_count_(
            [center], 1,
        )
        aPath.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_(
            center,
            radius,
            0,
            365 * (self.percentage / 100.),
        )
        aPath.appendBezierPathWithPoints_count_(
            [center], 1,
        )
        aPath.setLineWidth_(5)
        NSColor.blueColor().colorWithAlphaComponent_(1/4).setStroke()
        NSColor.redColor().colorWithAlphaComponent_(1/4).setFill()
        aPath.stroke()
        aPath.fill()

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
    return win                  # type: ignore


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
    _animationInProgress: Deferred[None] | None = None

    def animatePercentage(
        self,
        clock: IReactorTime,
        percentageElapsed: float,
        pulseTime: float = 1.0,
        baseAlphaValue: float = 0.15,
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

        self._animationInProgress = lc.start(1.0 / 60.0).addCallback(clear)
        self.show()
        return self._animationInProgress

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
        return NSFocusRingTypeNone  # type: ignore

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


def _removeWindows(self: ProgressController) -> None:
    """
    Remove the progress views from the given ProgressController.
    """
    self.progressViews = []
    self.hudWindows, oldHudWindows = [], self.hudWindows
    for eachWindow in oldHudWindows:
        eachWindow.close()
        eachWindow.setContentView_(None)
