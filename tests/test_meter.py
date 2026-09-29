import unittest
from unittest import mock

from jirafe.meter import RequestMeter


class RequestMeterTest(unittest.TestCase):

    def test_counts_by_window_and_origin(self):
        meter = RequestMeter()
        with mock.patch("jirafe.meter.time.monotonic", return_value=0):
            meter.record("sync")
        with mock.patch("jirafe.meter.time.monotonic", return_value=240):
            meter.record("page")
            meter.record("page")
        with mock.patch("jirafe.meter.time.monotonic", return_value=250):
            snapshot = meter.snapshot()
        self.assertEqual(
            snapshot["windows"]["1m"],
            {"total": 2, "byOrigin": {"page": 2}}
        )
        self.assertEqual(
            snapshot["windows"]["5m"]["byOrigin"],
            {"sync": 1, "page": 2}
        )
        self.assertEqual(snapshot["sinceStart"], 3)

    def test_forgets_after_fifteen_minutes(self):
        meter = RequestMeter()
        with mock.patch("jirafe.meter.time.monotonic", return_value=0):
            meter.record("page")
        with mock.patch("jirafe.meter.time.monotonic", return_value=16 * 60):
            snapshot = meter.snapshot()
        self.assertEqual(snapshot["windows"]["15m"]["total"], 0)
        self.assertEqual(snapshot["sinceStart"], 1)
