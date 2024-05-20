from __future__ import annotations

from AppKit import NSTableView
from datetype import DateTime
from Foundation import NSObject
from fritter.drivers.datetimes import guessLocalZone

from pomodouroboros.model.util import showFailures

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

    # This table is not editable.
    def tableView_shouldEditTableColumn_row_(
        self, tableView, shouldEditTableColumn, row
    ) -> bool:
        return False

    def tableView_setObjectValue_forTableColumn_row_(
        self,
        tableView: NSTableView,
        objectValue: NSObject,
        tableColumn: object,
        row: int,
    ) -> None:
        return None

    def tableView_objectValueForTableColumn_row_(
        self,
        tableView: NSTableView,
        objectValueForTableColumn: NSObject,
        row: int,
    ) -> dict[str, str]:
        with showFailures():
            session = self.nexus._sessions[row]
            startDT = DateTime.fromtimestamp(session.start, TZ)
            endDT = DateTime.fromtimestamp(session.end, TZ)
            return {
                "startTime": startDT.isoformat(sep=" ", timespec="minutes"),
                "endTime": endDT.isoformat(sep=" ", timespec="minutes"),
                # TODO: how to reload when intervals or points change?  (note,
                # this should only ever happen to the last session, since all
                # others are immutable...)
                "intervals": str(
                    len(
                        list(
                            self.nexus.intervalsBetween(
                                session.start, session.end
                            )
                        )
                    )
                ),
                "points": str(
                    sum(
                        each.points
                        for each in self.nexus.scoreEvents(
                            startTime=session.start, endTime=session.end
                        )
                    )
                ),
                "automatic": str(session.automatic),
            }
