from datetime import date, datetime, time
import json
from pathlib import Path
import unittest

from backend.forecast import SHANGHAI, StationForecast
from backend.ocr import ScreenshotReader, candidates_from_text
from backend.routing import StationRoutes

FIXTURE = json.loads(
    (Path(__file__).resolve().parents[1] / "backend" / "data" / "demo.json").read_text(encoding="utf-8")
)


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.routes = StationRoutes(FIXTURE["station"], FIXTURE["layout"])

    def test_combines_common_shelf_and_improves_input_order(self):
        result = self.routes.plan("ENT", ["C2", "A1", "C1", "A2", "A1"])
        self.assertEqual(result["stops"], ["A1", "A2", "C2", "C1"])
        self.assertEqual((result["baseline_distance_m"], result["distance_m"]), (95, 35))
        self.assertEqual(result["path"][-2:], ["VERIFY", "EXIT"])

    def test_replans_remaining_stops_from_current_shelf(self):
        result = self.routes.plan("A2", ["C2", "C1"])
        self.assertEqual(result["path"][0], "A2")
        self.assertEqual(result["stops"], ["C2", "C1"])
        self.assertEqual(result["distance_m"], 24)

    def test_preserves_reachable_shelves_when_one_is_closed(self):
        result = self.routes.plan("ENT", ["A1", "C2"], [("B2", "C2"), ("C1", "C2")])
        self.assertEqual(result["stops"], ["A1"])
        self.assertEqual(result["unreachable_shelves"], ["C2"])

    def test_requires_verification_before_exit(self):
        result = self.routes.plan("A2", [])
        self.assertEqual(result["stops"], [])
        self.assertEqual(result["path"][-2:], ["VERIFY", "EXIT"])
        with self.assertRaisesRegex(ValueError, "无法经核验点"):
            self.routes.plan("A2", [], [("VERIFY", "EXIT")])


class ForecastTests(unittest.TestCase):
    def setUp(self):
        rows = [(row["queue_joined_at"], row["service_started_at"], row["service_finished_at"])
                for row in FIXTURE["queue_observations"]]
        self.forecast = StationForecast(FIXTURE["station"], rows)

    def test_respects_opening_and_calculates_queue_arrival_after_search(self):
        day = date(2026, 11, 23)
        now = datetime.combine(day, time(8), SHANGHAI)
        trip = {"distance_m": 35, "to_verification_m": 32, "parcel_count": 5}
        result = self.forecast.recommendations(day, time(9), time(21), trip, now=now)
        options = result["candidates"]
        self.assertEqual(len(options), 20)
        self.assertEqual(min(item["time"] for item in options), "10:00")
        self.assertEqual(max(item["time"] for item in options), "19:30")
        self.assertTrue(all(item["queue_time"] > item["time"] for item in options))
        self.assertEqual(options[0]["wait_minutes"], min(item["wait_minutes"] for item in options))

    def test_closing_window_and_chronological_holdout(self):
        day = date(2026, 11, 23)
        now = datetime.combine(day, time(20), SHANGHAI)
        result = self.forecast.recommendations(day, time(18), time(22), now=now)
        self.assertEqual(result["candidates"], [])
        metrics = self.forecast.backtest(date(2026, 11, 16))
        self.assertEqual((metrics["train_count"], metrics["test_count"]), (816, 272))


class ScreenshotCandidateTests(unittest.TestCase):
    def test_keeps_leading_zero_and_requires_shelf_for_pickup_code(self):
        parsed = candidates_from_text([
            ("自取货号 C2－01－0356", .98),
            ("取件码：D803", .97),
            ("取件码：C2-01-0356", .97),
        ], {"C2"})
        self.assertEqual(parsed[0]["suffix"], "0356")
        self.assertEqual(parsed[0]["shelf"], "C2")
        self.assertFalse(parsed[0]["needs_shelf"])
        self.assertEqual(parsed[1]["code"], "D803")
        self.assertTrue(parsed[1]["needs_shelf"])

    def test_recognizes_actual_synthetic_notification_image(self):
        image = Path(__file__).with_name("fixtures") / "notice-demo.png"
        parsed = candidates_from_text(ScreenshotReader().read(image.read_bytes()), {"C2"})
        self.assertEqual([(row["code"], row["shelf"]) for row in parsed], [
            ("C2-01-6721", "C2"), ("D803", ""),
        ])


if __name__ == "__main__":
    unittest.main()
