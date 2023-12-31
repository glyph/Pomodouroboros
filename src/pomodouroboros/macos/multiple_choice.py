from __future__ import annotations

from typing import Callable, TypeVar

from AppKit import (
    NSBackingStoreBuffered,
    NSButton,
    NSClosableWindowMask,
    NSColor,
    NSCommandKeyMask,
    NSControlSizeLarge,
    NSImageLeading,
    NSLayoutAttributeHeight,
    NSLayoutAttributeWidth,
    NSLayoutConstraint,
    NSLayoutConstraintOrientationHorizontal,
    NSLayoutConstraintOrientationVertical,
    NSLineBreakByWordWrapping,
    NSPanel,
    NSStackView,
    NSStackViewDistributionFillProportionally,
    NSTitledWindowMask,
    NSUserInterfaceLayoutOrientationVertical,
    NSWindowCollectionBehaviorParticipatesInCycle,
    NSWindowStyleMaskFullSizeContentView,
    NSWindowStyleMaskHUDWindow,
    NSWindowStyleMaskResizable,
    NSWindowTitleHidden,
)
from Foundation import NSObject, NSRect
from objc import IBAction
from twisted.internet.defer import Deferred

from ..model.debugger import debug


T = TypeVar("T")


class CustomButton(NSButton):
    ...
    # def intrinsicContentSize(self) -> NSSize:
    #     return self.fittingSize()


class ChoiceAction(NSObject):
    def initWithFunc_(self, func: Callable[[], T]) -> ChoiceAction:
        self.func = func
        return self

    @IBAction
    def choose_(self, sender: NSObject) -> None:
        self.func()


def answerWith(deferred: Deferred[T], answer: T) -> Callable[[], None]:
    def answerer():
        debug("giving result", answer)
        deferred.callback(answer)

    return answerer


def oneButton(
    title: str,
    func: Callable[[], T],
    color: NSColor,
    key: str,
    mask: int = NSCommandKeyMask,
) -> NSButton:
    b = NSButton.buttonWithTitle_target_action_(
        title,
        ChoiceAction.alloc().initWithFunc_(func).retain(),
        "choose:",
    )
    b.setBezelColor_(color)
    b.setControlSize_(NSControlSizeLarge)
    b.setImage_(None)
    b.setAlternateImage_(None)
    b.setImagePosition_(NSImageLeading)
    b.setKeyEquivalent_(key)
    b.setKeyEquivalentModifierMask_(NSCommandKeyMask)
    b.setContentHuggingPriority_forOrientation_(
        1,
        NSLayoutConstraintOrientationHorizontal,
    )
    b.setContentHuggingPriority_forOrientation_(
        1,
        NSLayoutConstraintOrientationVertical,
    )
    b.setAlignment_(0)
    return b


async def multipleChoiceButtons(
    descriptions: list[tuple[NSColor, str, T]],
) -> T:
    d: Deferred[T] = Deferred()
    wide = CustomButton.buttonWithTitle_target_action_(
        "four score and seven years ago\nwe had a big pile\nof super wide buttons",
        None,
        None,
    )
    # wide.setButtonType_()
    wide.sizeToFit()
    wide.cell().setWraps_(True)
    wide.setControlSize_(NSControlSizeLarge)
    wide.setUsesSingleLineMode_(True)
    viewsToStack = []

    for index, (color, title, potentialAnswer) in enumerate(descriptions):
        # skew = 3
        key = index + 1
        b = oneButton(
            f"⌘{key} — {title}",
            answerWith(d, potentialAnswer),
            color,
            str(key),
        )
        # b.setTranslatesAutoresizingMaskIntoConstraints_(False)
        viewsToStack.append(b)

    stackView = NSStackView.stackViewWithViews_(viewsToStack)
    stackView.setOrientation_(NSUserInterfaceLayoutOrientationVertical)
    wrapperStackView = NSStackView.stackViewWithViews_([stackView])
    stackView.setEdgeInsets_((20, 20, 20, 20))
    stackView.setDistribution_(NSStackViewDistributionFillProportionally)
    wrapperStackView.setEdgeInsets_((20, 20, 20, 20))

    stackView.setContentHuggingPriority_forOrientation_(
        1,
        NSLayoutConstraintOrientationHorizontal,
    )
    stackView.setContentHuggingPriority_forOrientation_(
        1,
        NSLayoutConstraintOrientationVertical,
    )
    wrapperStackView.setContentHuggingPriority_forOrientation_(
        1,
        NSLayoutConstraintOrientationHorizontal,
    )
    wrapperStackView.setContentHuggingPriority_forOrientation_(
        1,
        NSLayoutConstraintOrientationVertical,
    )

    # sz = wrapperStackView.fittingSize()
    # debug("size?", sz)
    styleMask = (
        NSTitledWindowMask
        | (NSClosableWindowMask & 0)
        | NSWindowStyleMaskFullSizeContentView
        | NSWindowStyleMaskHUDWindow
        | NSWindowStyleMaskResizable
    )
    nsw = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
        NSRect((100, 100), (200, 100)),
        styleMask,
        NSBackingStoreBuffered,
        False,
    )
    nsw.setTitle_("Select Choice")
    nsw.setTitleVisibility_(NSWindowTitleHidden)
    nsw.setTitlebarAppearsTransparent_(True)
    nsw.setBecomesKeyOnlyIfNeeded_(False)
    nsw.setCollectionBehavior_(NSWindowCollectionBehaviorParticipatesInCycle)
    nsw.setContentView_(wrapperStackView)
    makeConstraints = (
        NSLayoutConstraint.constraintsWithVisualFormat_options_metrics_views_
    )
    for eachView in viewsToStack[1:]:
        stackView.addConstraints_(
            makeConstraints(
                "[follower(==leader)]",
                0,
                None,
                {"leader": viewsToStack[0], "follower": eachView},
            )
        )

    stackView.setAlignment_(NSLayoutAttributeWidth)
    wrapperStackView.setAlignment_(NSLayoutAttributeHeight)

    wide.frame().size.height = 100
    wide.cell().setLineBreakMode_(NSLineBreakByWordWrapping)

    nsw.setReleasedWhenClosed_(False)
    nsw.setHidesOnDeactivate_(False)
    nsw.center()
    nsw.makeKeyAndOrderFront_(nsw)

    result = await d
    nsw.close()
    return result
