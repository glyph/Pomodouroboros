from unittest import TestCase

from .pommodel import Day
from datetime import datetime, timezone, time, date


class DayTests(TestCase):
    """
    Tests for L{Day}
    """

    def test_simpleDay(self) -> None:
        """
        Create a day and see how many poms it's got.
        """
        simpleDay = Day.new(
            time(9),
            time(17),
            date(2021, 9, 1),
            timezone.utc,
            longBreaks=[5, 6],
        )
        self.assertEqual(
            len(simpleDay.pendingIntervals),
            (8 * 2 * 2)  # start with 8 hours broken into 2 poms, each pom
                         # broken into pom/break
            - 3,  # subtract out 3 breaks because the long breaks are
                  # contiguous (including contiguous with the previous
                  # pomodoro's break)
        )
