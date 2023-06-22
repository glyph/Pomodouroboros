from __future__ import annotations

from Foundation import NSObject
from AppKit import NSTextView

class TabOrderFriendlyTextViewDelegate(NSObject):
    """
    Act as a NSTextViewDelegate to allow for tab/backtab (i.e. shift-tab) to
    cycle through focus elements, since we're not going to be putting literal
    tabs into descriptions.
    """

    def textView_doCommandBySelector_(
        self, aTextView: NSTextView, aSelector: str
    ) -> bool:
        match aSelector:
            case "insertTab:":
                aTextView.window().selectNextKeyView_(None)
                return True
            case "insertBacktab:":
                aTextView.window().selectPreviousKeyView_(None)
                return True
            case _:
                return False


