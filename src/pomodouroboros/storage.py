from dataclasses import dataclass, field
from datetime import date as Date
from os import environ
from os.path import expanduser
from pickle import dumps, loads
from typing import Dict

from twisted.python.filepath import FilePath

from pomodouroboros.pommodel import Day


TEST_MODE = bool(environ.get("TEST_MODE"))

defaultBaseLocation = FilePath(expanduser("~/.local/share/pomodouroboros"))
if TEST_MODE:
    defaultBaseLocation = defaultBaseLocation.child("testing")


@dataclass
class DayLoader:
    baseLocation: FilePath = defaultBaseLocation
    cache: Dict[Date, Day] = field(default_factory=dict)

    def pathForDate(self, date: Date) -> FilePath:
        return self.baseLocation.child(date.isoformat() + ".pomday")

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
            print("cache hit", date, self.cache[date])
            return self.cache[date]

        dayPath = self.pathForDate(date)
        loadedOrCreated = (
            Day.forTesting()
            if TEST_MODE
            else loads(dayPath.getContent())
            if dayPath.isfile()
            else Day.new(day=date)
        )
        print("cache miss", date, loadedOrCreated)
        self.cache[date] = loadedOrCreated
        return loadedOrCreated
