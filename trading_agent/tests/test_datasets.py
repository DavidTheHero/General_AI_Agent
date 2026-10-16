"""Independent checks for immutable observation, provenance and rejection artifacts."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from trading_agent.calendar import MarketCalendar
from trading_agent.data import DataError, SyntheticFeed, YahooFinanceFeed
from trading_agent.datasets import DatasetStore, checksum, frame_record


class DatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.calendar = MarketCalendar()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        def cleanup():
            for directory in Path(self.temporary.name).rglob("*"):
                if directory.is_dir():
                    directory.chmod(0o755)
            self.temporary.cleanup()
        self.addCleanup(cleanup)
        self.store = DatasetStore(Path(self.temporary.name) / "datasets")
        self.request = {"source": "synthetic", "symbols": ["TEST"], "start": "2026-10-01", "end": "2026-10-02", "interval": "60m", "seed": 17}
        self.sessions = self.calendar.sessions(self.request["start"], self.request["end"])
        self.data = SyntheticFeed(self.sessions, seed=17).fetch(["TEST"], self.request["start"], self.request["end"], "60m")

    def test_raw_actions_adjusted_columns_and_request_are_preserved_and_checksummed(self):
        raw = self.data.frames["TEST"].copy()
        raw["Dividends"], raw["Stock Splits"], raw["Adj Close"] = 0.0, 0.0, raw.Close - 0.1
        response = {"symbol": "TEST", "frame": frame_record(raw), "metadata": {"currency": "USD"},
                    "request": {"auto_adjust": False, "actions": True, "interval": "60m"}, "retrieved_at": self.data.retrieved_at}
        manifest = self.store.save(self.data, self.request, raw_responses=[response], calendar=self.calendar)
        self.assertTrue(manifest["quality"]["usable"])
        directory = self.store.root / manifest["dataset_id"]
        self.assertEqual(json.loads((directory / "raw.json").read_text()), [response])
        for name, digest in manifest["files"].items():
            self.assertEqual(checksum(directory / name), digest)
        self.assertEqual(self.store.inspect(manifest["dataset_id"]), manifest)
        self.assertEqual(manifest["request"], self.request)
        self.assertEqual(manifest["observation_type"], "aggregated_ohlcv")
        self.assertIn("HTTP bytes unavailable", manifest["raw_capture_level"])

    def test_any_saved_observation_corruption_is_detected(self):
        manifest = self.store.save(self.data, self.request, calendar=self.calendar)
        path = self.store.root / manifest["dataset_id"] / "bars-0.json"
        path.chmod(0o644)
        path.write_text(path.read_text() + " ")
        with self.assertRaisesRegex(DataError, "checksum mismatch"):
            self.store.inspect(manifest["dataset_id"])
        with self.assertRaises(DataError):
            self.store.load(manifest["dataset_id"])

    def test_raw_nan_and_infinities_remain_distinguishable_in_rejected_evidence(self):
        data = deepcopy(self.data)
        offset = data.frames["TEST"].columns.get_loc("Close")
        data.frames["TEST"].iloc[:3, offset] = [float("nan"), float("inf"), float("-inf")]
        manifest = self.store.save(data, self.request, calendar=self.calendar)
        self.assertFalse(manifest["quality"]["usable"])
        directory = self.store.root / manifest["dataset_id"]
        raw = json.loads((directory / "raw.json").read_text())[0]["frame"]
        actual = [row[offset] for row in raw["data"][:3]]
        self.assertEqual(actual, [{"nonfinite": "nan"}, {"nonfinite": "inf"}, {"nonfinite": "-inf"}])
        self.assertEqual(checksum(directory / "raw.json"), manifest["files"]["raw.json"])
        with self.assertRaisesRegex(DataError, "quality failed"):
            self.store.load(manifest["dataset_id"])

    def test_gaps_and_dividends_are_saved_as_unusable_without_repair(self):
        for kind in ["gap", "dividend"]:
            data = deepcopy(self.data)
            raw_responses = None
            if kind == "gap":
                data.frames["TEST"] = data.frames["TEST"].iloc[1:]
            else:
                raw = data.frames["TEST"].copy()
                raw["Dividends"] = 0.0
                raw.iloc[0, raw.columns.get_loc("Dividends")] = 0.5
                raw_responses = [{"symbol": "TEST", "frame": frame_record(raw)}]
            manifest = self.store.save(data, self.request, raw_responses=raw_responses, calendar=self.calendar)
            with self.subTest(kind=kind):
                self.assertFalse(manifest["quality"]["usable"])
                self.assertTrue(manifest["quality"]["errors"])
                self.assertEqual(manifest["quality"]["instruments"]["TEST"]["missing_count"], 1 if kind == "gap" else 0)
                self.assertEqual(manifest["quality"]["corporate_action_count"], 1 if kind == "dividend" else 0)
                self.assertEqual(manifest["request"], self.request)
                with self.assertRaisesRegex(DataError, "quality failed"):
                    self.store.load(manifest["dataset_id"])

    def test_unsupported_exchange_or_currency_cannot_be_used(self):
        for currency, exchange in [("GBP", "NMS"), ("USD", "LSE"), ("USD", None)]:
            data = deepcopy(self.data)
            data.source = "Yahoo fixture"
            data.metadata["TEST"] = {"currency": currency, "exchange": exchange}
            manifest = self.store.save(data, self.request, calendar=self.calendar)
            with self.subTest(currency=currency, exchange=exchange):
                self.assertFalse(manifest["quality"]["usable"])
                self.assertTrue(any("currency" in error or "exchange" in error for error in manifest["quality"]["errors"]))

    def test_failed_yahoo_later_batch_preserves_earlier_response_and_error(self):
        request = {**self.request, "source": "yahoo", "end": "2026-10-14", "interval": "1m"}
        raw = SyntheticFeed(self.sessions[:1], seed=17).fetch(["TEST"], "2026-10-01", "2026-10-01", "1m").frames["TEST"]
        class Ticker:
            calls = 0
            def history(self, **kwargs):
                self.calls += 1
                if self.calls > 1:
                    raise RuntimeError("Deliberate later-batch failure")
                return raw
            def get_history_metadata(self): return {"currency": "USD", "exchangeName": "NMS", "exchangeTimezoneName": "America/New_York"}
        ticker = Ticker()
        def feed(**kwargs):
            return YahooFinanceFeed(lambda symbol: ticker, clock=lambda: pd.Timestamp("2026-10-15T20:00Z"), **kwargs)
        with patch("trading_agent.datasets.YahooFinanceFeed", side_effect=feed), self.assertRaisesRegex(DataError, "later-batch failure"):
            self.store.acquire(request, calendar=self.calendar)
        acquisition = next((self.store.root / "acquisitions").iterdir())
        self.assertEqual(json.loads((acquisition / "request.json").read_text()), request)
        responses = sorted(acquisition.glob("response-*.json"))
        self.assertEqual(len(responses), 2)
        first, second = [json.loads(path.read_text()) for path in responses]
        self.assertEqual(first["frame"], frame_record(raw))
        self.assertEqual(first["request"]["interval"], "1m")
        self.assertEqual(first["request"]["start"], "2026-10-01")
        self.assertIsNone(second["frame"])
        self.assertIn("later-batch failure", second["error"])
        failure = json.loads((acquisition / "failure.json").read_text())
        self.assertEqual(len(failure["responses"]), 2)
        for item in failure["responses"]:
            self.assertEqual(checksum(acquisition / item["file"]), item["sha256"])
        self.assertFalse(list(self.store.root.glob("*/manifest.json")))

    def test_seeded_values_reproduce_while_acquisition_timestamps_get_distinct_ids(self):
        manifests = [self.store.acquire(self.request, calendar=self.calendar) for _ in range(2)]
        self.assertNotEqual(manifests[0]["dataset_id"], manifests[1]["dataset_id"])
        first, _ = self.store.load(manifests[0]["dataset_id"])
        second, _ = self.store.load(manifests[1]["dataset_id"])
        pd.testing.assert_frame_equal(first.frames["TEST"], second.frames["TEST"])
        for manifest in manifests:
            self.assertEqual(manifest["request"], self.request)
            self.assertEqual(manifest["sessions"], [session.date for session in self.sessions])
            self.assertEqual(manifest["quality"]["instruments"]["TEST"]["rows"], 14)

    def test_metadata_failure_still_preserves_the_returned_provider_frame(self):
        request = {**self.request, "source": "yahoo"}
        raw = self.data.frames["TEST"]
        class Ticker:
            def history(self, **kwargs): return raw
            def get_history_metadata(self): raise RuntimeError("Deliberate metadata failure")
        def feed(**kwargs):
            return YahooFinanceFeed(lambda symbol: Ticker(), clock=lambda: pd.Timestamp("2026-10-15T20:00Z"), **kwargs)
        with patch("trading_agent.datasets.YahooFinanceFeed", side_effect=feed), self.assertRaisesRegex(DataError, "metadata failure"):
            self.store.acquire(request, calendar=self.calendar)
        acquisition = next((self.store.root / "acquisitions").iterdir())
        responses = list(acquisition.glob("response-*.json"))
        self.assertEqual(len(responses), 1)
        response = json.loads(responses[0].read_text())
        self.assertEqual(response["frame"], frame_record(raw))
        self.assertIn("metadata failure", response["error"])
        self.assertEqual(response["request"]["start"], request["start"])
        self.assertEqual(response["request"]["interval"], request["interval"])
        failure = json.loads((acquisition / "failure.json").read_text())
        self.assertEqual(failure["responses"][0]["sha256"], checksum(responses[0]))
        self.assertFalse(list(self.store.root.glob("*/manifest.json")))


if __name__ == "__main__":
    unittest.main()
