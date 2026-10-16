"""Real daily research contracts tested with explicit provider fixtures, never a model."""
from copy import deepcopy
from collections.abc import Mapping
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

import numpy as np
import pandas as pd
from pydantic import ValidationError

from trading_agent.calendar import MarketCalendar
from trading_agent.daily_research import DailyResearchSpec, acquire_daily, load_daily, paired_evidence, run_daily_research
from trading_agent.data import DataError


class DailyResearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = DailyResearchSpec(data_start="2019-01-02", development_start="2020-01-02", validation_start="2021-01-04",
                                    development_end="2022-12-30", lookbacks=[63], cost_bps=[5.0])
        dates = [session.date for session in MarketCalendar().sessions(cls.spec.data_start, cls.spec.development_end)]
        index = pd.DatetimeIndex(dates).tz_localize("America/New_York")
        cls.frames = {}
        for number, symbol in enumerate(cls.spec.symbols):
            prices = 100 * np.exp(np.arange(len(index)) * (0.0002 + number * 0.0001))
            cls.frames[symbol] = pd.DataFrame({"Open": prices, "High": prices * 1.01, "Low": prices * .99,
                "Close": prices, "Adj Close": prices, "Volume": 10000, "Dividends": 0.0, "Stock Splits": 0.0}, index=index)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.calls = []

    def tearDown(self):
        self.temporary.cleanup()

    def factory(self, symbol):
        owner = self
        class Ticker:
            def history(self, **kwargs):
                owner.calls.append((symbol, kwargs))
                return owner.frames[symbol].copy()
            def get_history_metadata(self):
                return {"currency": "USD", "exchangeTimezoneName": "America/New_York"}
        return Ticker()

    def test_real_request_is_exact_archived_and_never_fetches_reserved_period(self):
        frames, manifest = acquire_daily(self.spec, self.root / "data", ticker_factory=self.factory)
        self.assertTrue(manifest["quality"]["usable"])
        self.assertFalse(manifest["final_period_requested"])
        self.assertEqual(len(frames), 3)
        for symbol, request in self.calls:
            self.assertEqual(request["end"], "2022-12-31")
            self.assertFalse(request["auto_adjust"])
            self.assertFalse(request["repair"])
            self.assertTrue(request["actions"])
            self.assertTrue(request["keepna"])
            saved = json.loads((self.root / "data" / f"raw-{symbol}.json").read_text())
            self.assertIn("Dividends", saved["frame"]["columns"])
            self.assertEqual(saved["metadata"]["fields"]["currency"], "USD")
        loaded, saved = load_daily(self.root / "data")
        self.assertEqual(saved, manifest)
        np.testing.assert_allclose(loaded["SPY"]["Adj Close"], self.frames["SPY"]["Adj Close"])

    def test_lazy_provider_metadata_does_not_trigger_an_intraday_request(self):
        class Metadata(Mapping):
            def __iter__(self): return iter(["currency", "exchangeTimezoneName", "tradingPeriods"])
            def __len__(self): return 3
            def __getitem__(self, key):
                if key == "tradingPeriods":
                    raise AssertionError("Lazy intraday metadata must not be requested")
                return {"currency": "USD", "exchangeTimezoneName": "America/New_York"}[key]
        owner = self
        class Ticker:
            def __init__(self, symbol): self.symbol = symbol
            def history(self, **_kwargs): return owner.frames[self.symbol]
            def get_history_metadata(self): return Metadata()
        _, manifest = acquire_daily(self.spec, self.root / "data", ticker_factory=Ticker)
        self.assertEqual(manifest["metadata"]["SPY"]["fields"]["currency"], "USD")
        self.assertIn("not evaluated", manifest["metadata"]["SPY"]["omissions"][0])

    def test_corruption_and_provider_failure_leave_explicit_evidence(self):
        acquire_daily(self.spec, self.root / "data", ticker_factory=self.factory)
        path = self.root / "data/raw-SPY.json"
        path.chmod(0o644)
        path.write_text(path.read_text() + " ")
        with self.assertRaisesRegex(DataError, "checksum mismatch"):
            load_daily(self.root / "data")
        class FailedTicker:
            def history(self, **_kwargs): raise RuntimeError("fixture unavailable")
        with self.assertRaisesRegex(DataError, "fixture unavailable"):
            acquire_daily(self.spec, self.root / "failed", ticker_factory=lambda _: FailedTicker())
        self.assertTrue((self.root / "failed/raw-SPY.json").is_file())
        self.assertTrue((self.root / "failed/failure.json").is_file())

    def test_gap_is_not_filled_or_request_shortened(self):
        bad = deepcopy(self.frames)
        bad["IEF"] = bad["IEF"].iloc[1:]
        with patch.object(self, "frames", bad), self.assertRaisesRegex(DataError, "quality failed"):
            acquire_daily(self.spec, self.root / "data", ticker_factory=self.factory)
        manifest = json.loads((self.root / "data/manifest.json").read_text())
        self.assertEqual(manifest["quality"]["instruments"]["IEF"]["missing_count"], 1)
        self.assertFalse(manifest["quality"]["usable"])

    def test_study_freezes_training_selection_records_attempts_and_reconciles(self):
        experiment_id = uuid4().hex
        with patch("trading_agent.daily_research.paired_evidence", return_value={"assessment": "inconclusive"}):
            result = run_daily_research(self.spec, self.root / "research", self.root / "output", experiment_id, ticker_factory=self.factory)
        self.assertEqual(result["status"], "complete", result["errors"])
        self.assertEqual(result["promotion_status"], "research_only")
        self.assertFalse(result["reserved_final"]["accessed"])
        self.assertEqual(len(result["attempts"]), 8)
        self.assertEqual({item["end"] for item in result["attempts"] if item["period"].startswith("validation")}, {"2022-12-30"})
        for attempt in result["attempts"]:
            self.assertTrue(attempt["reconciliation"]["ok"])
            self.assertTrue((self.root / "research" / attempt["artifact_ref"]).is_file())
        self.assertEqual(set(result["selected_by_training"]), {"sma_cash", "relative_momentum"})
        self.assertEqual(result["source_snapshot"], result["environment"]["source_sha256"])
        # Exact snapshot reuse does not silently replace the requested dataset.
        calls = len(self.calls)
        with patch("trading_agent.daily_research.paired_evidence", return_value={"assessment": "inconclusive"}):
            replay = run_daily_research(self.spec, self.root / "research", self.root / "replay", uuid4().hex, ticker_factory=self.factory)
        self.assertEqual(len(self.calls), calls)
        self.assertEqual(replay["dataset_id"], result["dataset_id"])
        self.assertEqual(replay["metrics"], result["metrics"])
        self.assertIn("Reused", replay["data_acquisition"])

    def test_cancelled_attempt_and_failed_final_reservation_are_recorded(self):
        with patch("trading_agent.daily_screen.simulate_daily", side_effect=KeyboardInterrupt()):
            result = run_daily_research(self.spec, self.root / "research", self.root / "output", uuid4().hex, ticker_factory=self.factory)
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["attempts"][0]["status"], "cancelled")
        self.assertFalse(result["attempts"][0]["artifact_available"])
        changed = self.spec.model_copy(update={"reserved_final_start": "2023-02-01"})
        failed = run_daily_research(changed, self.root / "research", self.root / "failed", uuid4().hex, ticker_factory=self.factory)
        self.assertEqual(failed["status"], "failed")
        self.assertIn("different final period", failed["errors"][0])

    def test_bounded_parameters_and_chronology(self):
        for update in [{"lookbacks": [2]}, {"cost_bps": [20.0, 5.0]}, {"symbols": ["AAPL"]},
                       {"development_end": "2024-01-01"}, {"data_start": "2019-06-01"}]:
            with self.assertRaises(ValidationError):
                DailyResearchSpec.model_validate({**self.spec.model_dump(), **update})

    def test_paired_bootstrap_distinguishes_growth_from_incremental_value(self):
        dates = pd.date_range("2018-01-31", periods=36, freq="ME")
        def result(rate):
            return {"metrics": {"initial_equity": 100}, "rows": [{"date": stamp.date().isoformat(), "equity": float(100 * (1 + rate)**(number + 1))} for number, stamp in enumerate(dates)]}
        self.assertEqual(paired_evidence(result(.01), result(.02), configurations=6)["assessment"], "rejects_alpha_claim")
        self.assertEqual(paired_evidence(result(.02), result(.01), configurations=6)["assessment"], "promising_requires_replication")
        self.assertEqual(paired_evidence(result(.01), result(.01), configurations=6)["assessment"], "inconclusive")


if __name__ == "__main__":
    unittest.main()
