from unittest import TestCase

from AppKit import (
    NSNib,
    NSObject,
    NSWindow,
    NSWorkspace,
    NSWorkspaceActiveSpaceDidChangeNotification,
)
from objc import IBOutlet

from ..progress_hud import PieTimer
from ..hudmulti import HUDMultipleProgress


class NibInitializationTests(TestCase):
    def setUp(self) -> None:
        self.NIB_NAMES = ["left", "middle", "right"]

        self.nibInstance = NSNib.alloc().initWithNibNamed_bundle_(
            "ProgressHUD.nib", None
        )
        self.owner = HUDMultipleProgress.alloc().init().retain()

    def test_nib_init(self) -> None:

        for nib_name in self.NIB_NAMES:
            self.assertIsNone(
                getattr(self.owner, nib_name),
                f"The nib called owner.{nib_name} was instantiated early!"
            )

        loaded, tlos = self.nibInstance.instantiateWithOwner_topLevelObjects_(
            self.owner, None
        )

        for nib_name in self.NIB_NAMES:
            self.assertIsNotNone(
                getattr(self.owner, nib_name),
                f"The nib called owner.{nib_name} was instantiated early!"
            )

