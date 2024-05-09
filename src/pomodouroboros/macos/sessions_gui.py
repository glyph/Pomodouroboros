from __future__ import annotations


from datetype import DateTime
from fritter.drivers.datetimes import guessLocalZone

from AppKit import NSTableView
from Foundation import NSObject

from ..model.nexus import Nexus

TZ = guessLocalZone()


class SessionDataSource(NSObject):
    """
    NSTableViewDataSource for the list of active sessions.
    """

    nexus: Nexus

    def awakeWithNexus_(self, newNexus: Nexus) -> None:
        self.nexus = newNexus

    # pragma mark NSTableViewDataSource

    def numberOfRowsInTableView_(self, tableView: NSTableView) -> int:
        return len(self.nexus._sessions)

    def tableView_objectValueForTableColumn_row_(
        self,
        tableView: NSTableView,
        objectValueForTableColumn: NSObject,
        row: int,
    ) -> dict[str, str]:
        session = self.nexus._sessions[row]
        dt = DateTime.fromtimestamp(session.start, TZ)
        return {
            "startTime": dt.isoformat(),
            "endTime": str(session.end),
            "intervals": "interval count",
            "points": "...",
            "automatic": str(session.automatic),
        }
