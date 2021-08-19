from pomodouroboros.pommodel import Day
from datetime import date as Date
from twisted.python.filepath import FilePath
from os.path import expanduser
from os import environ
from pickle import loads, dumps

TEST_MODE = bool(environ.get("TEST_MODE"))

baseLocation = FilePath(expanduser("~/.local/share/pomodouroboros"))
if TEST_MODE:
    baseLocation = baseLocation.child("testing")



def pathForDate(date: Date) -> FilePath:
    return baseLocation.child(date.isoformat() + ".pomday")


def saveDay(day: Day) -> None:
    """
    Save the given C{day} object.
    """
    if not baseLocation.isdir():
        baseLocation.makedirs(True)
    pathForDate(day.startTime.date()).setContent(dumps(day))


def loadOrCreateDay(date: Date) -> Day:
    """
    Load or create a day.
    """
    dayPath = pathForDate(date)
    if dayPath.isfile():
        return loads(dayPath.getContent())
    else:
        return Day.new(day=date)
