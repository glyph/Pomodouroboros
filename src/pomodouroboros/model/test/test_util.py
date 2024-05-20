from unittest import TestCase

from pomodouroboros.model.util import AMPM, addampm, ampmify


class AMPMTests(TestCase):
    def test_ampmFunctions(self) -> None:
        def check(hour12: int, ampm: AMPM, hour24: int) -> None:
            self.assertEqual(ampmify(hour12, ampm), hour24)
            self.assertEqual(addampm(hour24), (hour12, ampm))

        check(12, "AM", 0)
        check(1, "AM", 1)
        check(2, "AM", 2)
        check(3, "AM", 3)
        check(4, "AM", 4)
        check(5, "AM", 5)
        check(6, "AM", 6)
        check(7, "AM", 7)
        check(8, "AM", 8)
        check(9, "AM", 9)
        check(10, "AM", 10)
        check(11, "AM", 11)
        check(12, "PM", 12)
        check(1, "PM", 13)
        check(2, "PM", 14)
        check(3, "PM", 15)
        check(4, "PM", 16)
        check(5, "PM", 17)
        check(6, "PM", 18)
        check(7, "PM", 19)
        check(8, "PM", 20)
        check(9, "PM", 21)
        check(10, "PM", 22)
        check(11, "PM", 23)

    def test_outOfRange(self) -> None:
        with self.assertRaises(ValueError):
            addampm(25)
        with self.assertRaises(ValueError):
            ampmify(13, "AM")
