from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import wraps
from textwrap import dedent
from typing import TYPE_CHECKING, Any, Callable, Generic, Sequence, TypeVar

import objc
from AppKit import (NSApplication, NSApplicationActivationPolicyRegular,
                    NSColor, NSMakeRect, NSMakeSize, NSMenu, NSMenuItem, NSNib,
                    NSNotification, NSRect, NSSize, NSTableView, NSTextField,
                    NSTextFieldCell, NSTextView, NSWindow)
from Foundation import NSIndexSet, NSObject
from objc import IBAction, IBOutlet, super
from pomodouroboros.macos.mac_utils import Attr, SometimesBackground
from quickmacapp import Status, mainpoint
from twisted.internet.interfaces import IReactorTime
from twisted.internet.task import LoopingCall

from ..hasher import IDHasher
from ..model.intention import Intention
from ..model.intervals import AnyInterval, Pomodoro, StartPrompt
from ..model.nexus import Nexus
from ..model.storage import loadDefaultNexus
from ..storage import TEST_MODE
from .mac_utils import Forwarder, showFailures
from .old_mac_gui import main as oldMain
from .progress_hud import ProgressController

leftPadding = 15.0


class HeightSizableTextField(NSTextField):
    """
    Thanks https://stackoverflow.com/a/10463761/13564
    """

    def intrinsicContentSize(self) -> NSSize:
        """
        Calculate the intrinsic content size based on height.
        """
        if not self.cell().wraps():
            return super().intrinsicContentSize()

        frame = self.frame()
        width = 350.0  # frame.size.width
        origHeight = frame.size.height
        frame.size.height = 99999.0
        cellHeight = self.cell().cellSizeForBounds_(frame).height
        height = cellHeight + (leftPadding * 2)
        return NSMakeSize(width, height)

    def textDidChange_(self, notification: NSNotification) -> None:
        """
        The text changed, recalculate please
        """
        super().textDidChange_(notification)
        self.invalidateIntrinsicContentSize()

    @classmethod
    def cellClass(cls) -> type[PaddedTextFieldCell]:
        """
        Customize the cell class so that it includes some padding

        @note: C{cellClass} is nominally deprecated (as is C{cell}), but there
            doesn't seem to be any reasonable way to do this sort of basic
            customization that I{isn't} deprecated.  It seems like Apple mainly
            wants to deprecate the use of this customization mechanism in
            NSTableView usage?
        """
        return PaddedTextFieldCell


class PaddedTextFieldCell(NSTextFieldCell):
    """
    NSTextFieldCell subclass that adds some padding so it looks a bit more
    legible in the context of a popup menu label, with horizontal and vertical
    padding so that it is offset from the menu items.
    """

    def drawingRectForBounds_(self, rect: NSRect) -> NSRect:
        """
        Compute an inset drawing rect for the text.
        """
        rectInset = NSMakeRect(
            rect.origin.x + leftPadding,
            rect.origin.y + leftPadding,
            rect.size.width - (leftPadding * 2),
            rect.size.height - (leftPadding * 2),
        )
        return super().drawingRectForBounds_(rectInset)


def makeMenuLabel(menu: NSMenu, index: int = 0) -> HeightSizableTextField:
    """
    Make a multi-line label in the given menu that will be height-sized to its
    height.
    """
    viewItem = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "ignored", "doIt:", "k"
    )
    menu.insertItem_atIndex_(viewItem, 0)
    explanatoryLabel: HeightSizableTextField = (
        HeightSizableTextField.wrappingLabelWithString_("Starting Up…")
    )
    viewItem.setView_(explanatoryLabel)
    explanatoryLabel.setMaximumNumberOfLines_(100)
    explanatoryLabel.setSelectable_(False)
    explanatoryLabel.setTextColor_(NSColor.secondaryLabelColor())
    return explanatoryLabel

