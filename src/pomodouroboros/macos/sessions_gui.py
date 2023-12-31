from __future__ import annotations

from AppKit import NSTableView
from Foundation import NSObject

from ..model.nexus import Nexus


class SessionDataSource(NSObject):
    """
    NSTableViewDataSource for the list of active sessions.
    """

    def awakeWithNexus_(self, newNexus: Nexus) -> None:
        ...

    # pragma mark NSTableViewDataSource

    def numberOfRowsInTableView_(self, tableView: NSTableView) -> int:
        return 1

    def tableView_objectValueForTableColumn_row_(
        self,
        tableView: NSTableView,
        objectValueForTableColumn: NSObject,
        row: int,
    ) -> dict[str, str]:
        return {
            "startTime": "start time here",
            "endTime": "end time here",
            "intervals": "interval count",
            "points": "how many points earned this session",
            "automatic": "was this session auto-started",
        }
