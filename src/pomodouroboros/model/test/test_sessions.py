from datetime import datetime, time
from unittest import TestCase
from zoneinfo import ZoneInfo

from datetype import aware

from pomodouroboros.model.sessions import DailySessionRule, Session, Weekday

PT = ZoneInfo("America/Los_Angeles")

testingRule = DailySessionRule(
    aware(time(3, 4, 5, tzinfo=PT), ZoneInfo),
    aware(time(4, 5, 6, tzinfo=PT), ZoneInfo),
    days={Weekday.tuesday, Weekday.wednesday, Weekday.friday},
)


class SessionGenerationTests(TestCase):
    def test_sameDay(self) -> None:
        desiredStart = aware(
            datetime(2023, 11, 7, 3, 4, 5, tzinfo=PT), ZoneInfo
        ).timestamp()
        desiredEnd = aware(
            datetime(2023, 11, 7, 4, 5, 6, tzinfo=PT), ZoneInfo
        ).timestamp()
        self.assertEqual(
            testingRule.nextAutomaticSession(
                aware(datetime(2023, 11, 7, 2, tzinfo=PT), ZoneInfo)
            ),
            Session(desiredStart, desiredEnd, True),
        )

    def test_nextDay(self) -> None:
        desiredStart = aware(
            datetime(2023, 11, 8, 3, 4, 5, tzinfo=PT), ZoneInfo
        ).timestamp()
        desiredEnd = aware(
            datetime(2023, 11, 8, 4, 5, 6, tzinfo=PT), ZoneInfo
        ).timestamp()
        self.assertEqual(
            testingRule.nextAutomaticSession(
                aware(datetime(2023, 11, 7, 8, tzinfo=PT), ZoneInfo)
            ),
            Session(desiredStart, desiredEnd, True),
        )

    def test_skipDay(self) -> None:
        desiredStart = aware(
            datetime(2023, 11, 10, 3, 4, 5, tzinfo=PT), ZoneInfo
        ).timestamp()
        desiredEnd = aware(
            datetime(2023, 11, 10, 4, 5, 6, tzinfo=PT), ZoneInfo
        ).timestamp()
        self.assertEqual(
            testingRule.nextAutomaticSession(
                aware(datetime(2023, 11, 8, 8, tzinfo=PT), ZoneInfo)
            ),
            Session(desiredStart, desiredEnd, True),
        )

    def test_noDays(self) -> None:
        noDaysRule = DailySessionRule(
            aware(time(3, 4, 5, tzinfo=PT), ZoneInfo),
            aware(time(4, 5, 6, tzinfo=PT), ZoneInfo),
            days=set(),
        )
        self.assertIs(
            noDaysRule.nextAutomaticSession(
                aware(datetime(2023, 11, 8, 8, tzinfo=PT), ZoneInfo)
            ),
            None,
        )
