from dataclasses import dataclass, field
from datetime import date as Date
from os import environ
from os.path import expanduser
from pickle import dumps, loads
from typing import Dict

from twisted.python.filepath import FilePath

from .pommodel import Day

TEST_MODE = bool(
    environ.get("TEST_MODE")
    or environ.get("ARGVZERO", "").endswith("/TestPomodouroboros")
)

defaultBaseLocation = FilePath(expanduser("~/.local/share/pomodouroboros"))
if TEST_MODE:
    defaultBaseLocation = defaultBaseLocation.child("testing")


@dataclass
class DayLoader:
    baseLocation: FilePath = defaultBaseLocation
    cache: Dict[Date, Day] = field(default_factory=dict)

    def pathForDate(self, date: Date) -> FilePath:
        childPath: FilePath = self.baseLocation.child(
            date.isoformat() + ".pomday"
        )
        return childPath

    def saveDay(self, day: Day) -> None:
        """
        Save the given C{day} object.
        """
        if not self.baseLocation.isdir():
            self.baseLocation.makedirs(True)
        self.pathForDate(day.startTime.date()).setContent(dumps(day))

    def loadOrCreateDay(self, date: Date) -> Day:
        """
        Load or create a day.
        """
        if date in self.cache:
            return self.cache[date]

        dayPath = self.pathForDate(date)
        loadedOrCreated: Day = (
            Day.forTesting()
            if TEST_MODE
            else loads(dayPath.getContent())
            if dayPath.isfile()
            else Day.new(day=date)
        )
        self.cache[date] = loadedOrCreated
        return loadedOrCreated
