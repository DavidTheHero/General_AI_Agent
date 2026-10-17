"""Frozen sector-study orchestration; arithmetic is covered by sector engine fixtures."""
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
from contextlib import closing
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

import pandas as pd
from pydantic import ValidationError

from trading_agent.calendar import MarketCalendar
from trading_agent.daily_research import acquire_daily_observations, paired_evidence
from trading_agent.daily_screen import SECTOR_UNIVERSE
from trading_agent.sector_research import SectorResearchSpec, run_sector_research


class SectorResearchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "research"
        self.output = Path(self.temporary.name) / "output"
        index = pd.DatetimeIndex(["2016-09-16", "2016-09-19", "2016-09-20"], tz="America/New_York")
        self.frames = {symbol: pd.DataFrame({"Open": 100.0, "High": 100.0, "Low": 100.0, "Close": 100.0,
                                             "Adj Close": 100.0, "Volume": 1000000.0}, index=index)
                       for symbol in SECTOR_UNIVERSE}
        self.manifest = {"source": "explicit provider fixture", "dataset_id": "a" * 64,
            "request": {"symbols": list(SECTOR_UNIVERSE), "start": "2000-01-03", "end_exclusive": "2022-12-31",
                        "interval": "1d", "auto_adjust": False, "back_adjust": False, "actions": True,
                        "repair": False, "keepna": True, "prepost": False, "rounding": False},
            "metadata": {symbol: {"fields": {"currency": "USD"}} for symbol in SECTOR_UNIVERSE},
            "quality": {"usable": True, "warnings": ["Explicit fixture; no strategy evidence"]}}

    def acquire(self, spec, directory, **_kwargs):
        self.assertEqual(spec, SectorResearchSpec())
        directory.mkdir()
        (directory / "manifest.json").write_text(json.dumps(self.manifest))
        return self.frames, self.manifest

    def simulate(self, frames, policy, start, end, *, cost_bps, initial_cash):
        self.assertIs(frames, self.frames)
        self.assertLess(end, "2023-01-03")
        # Deliberately make every sensitivity beat both references and the primary lose.
        cagr = 6.0 if policy.kind == "sector_momentum" and (policy.lookback, policy.holdings) == (252, 3) else 20.0 if policy.kind == "sector_momentum" else 8.0
        return {"policy": policy.model_dump(), "metrics": {"initial_equity": initial_cash, "cagr_pct": cagr,
                "final_equity": initial_cash * (1 + cagr / 100), "max_drawdown_pct": 10.0,
                "total_cost": cost_bps * 100}, "rows": [{"date": start, "equity": initial_cash}],
                "fills": [], "decisions": []}

    def evidence(self, candidate, benchmark, *, configurations):
        assessment = "promising_requires_replication" if candidate["metrics"]["cagr_pct"] > benchmark["metrics"]["cagr_pct"] else "rejects_alpha_claim"
        return {"assessment": assessment, "family_configurations": configurations}

    def run_study(self, *, simulate=None, acquire=None):
        experiment_id = uuid4().hex
        with patch("trading_agent.sector_research.acquire_daily_observations", side_effect=acquire or self.acquire) as acquisition, \
             patch("trading_agent.sector_research.load_daily", return_value=(self.frames, self.manifest)) as loaded, \
             patch("trading_agent.sector_research.simulate_sector_daily", side_effect=simulate or self.simulate) as simulation, \
             patch("trading_agent.sector_research.reconcile_daily_proxy", return_value={"ok": True, "errors": []}) as reconciliation, \
             patch("trading_agent.sector_research.paired_evidence", side_effect=self.evidence) as evidence, \
             patch("trading_agent.sector_reporting.write_sector_report") as report:
            record = run_sector_research({}, self.root, self.output, experiment_id)
        return record, {"acquisition": acquisition, "loaded": loaded, "simulation": simulation,
                        "reconciliation": reconciliation, "evidence": evidence, "report": report}

    def test_protocol_dates_universe_costs_and_capital_are_frozen(self):
        spec = SectorResearchSpec().model_dump()
        for update in [{"source": "stooq"}, {"symbols": list(reversed(SECTOR_UNIVERSE))},
                       {"data_start": "2000-01-04"}, {"development_start": "2002-01-02"},
                       {"validation_start": "2014-01-02"}, {"development_end": "2023-12-29"},
                       {"reserved_final_start": "2024-01-02"}, {"reserved_final_end": "2026-12-31"},
                       {"initial_cash": 99999.0}, {"cost_bps": [5.0, 20.0, 10.0]},
                       {"cost_bps": [5.0, 10.0, 30.0]}, {"lookback": 63}]:
            with self.subTest(update=update), self.assertRaises(ValidationError):
                SectorResearchSpec.model_validate({**spec, **update})

    def test_all_24_attempts_persist_and_sensitivity_cannot_replace_primary(self):
        result, mocks = self.run_study()
        self.assertEqual(result["status"], "complete", result["errors"])
        self.assertEqual(len(result["attempts"]), 24)
        self.assertEqual(mocks["simulation"].call_count, 24)
        self.assertEqual(mocks["reconciliation"].call_count, 24)
        self.assertEqual(len({item["attempt_id"] for item in result["attempts"]}), 24)
        self.assertEqual(len([item for item in result["attempts"] if item["period"] == "training"]), 4)
        self.assertEqual(len([item for item in result["attempts"] if item["period"] == "training_benchmark"]), 2)
        self.assertEqual(len([item for item in result["attempts"] if item["period"] == "validation"]), 12)
        self.assertEqual(len([item for item in result["attempts"] if item["period"] == "validation_benchmark"]), 6)
        self.assertEqual({(item["lookback"], item["holdings"]) for item in result["candidate_grid"]},
                         {(126, 1), (126, 3), (252, 1), (252, 3)})
        self.assertEqual((result["primary_policy"]["lookback"], result["primary_policy"]["holdings"]), (252, 3))
        self.assertEqual(result["assessment"], "rejects_alpha_claim")
        self.assertEqual(result["promotion_status"], "research_only")
        self.assertFalse(result["reserved_final"]["accessed"])
        self.assertEqual(len(result["comparisons"]), 24)
        primary = [item for item in result["comparisons"] if item["primary"]]
        self.assertEqual(len(primary), 6)
        self.assertEqual({item["cost_bps"] for item in primary}, {5.0, 10.0, 20.0})
        self.assertEqual({item["benchmark"] for item in primary}, {"sector_equal_weight", "buy_hold"})
        self.assertTrue(all(item["evidence"]["assessment"] == "promising_requires_replication"
                            for item in result["comparisons"] if not item["primary"]))
        self.assertEqual(result["multiple_testing"]["correction_configurations"], 10)
        self.assertEqual({call.kwargs["configurations"] for call in mocks["evidence"].call_args_list}, {10})
        self.assertEqual(result["source_snapshot"], result["environment"]["source_sha256"])
        for attempt in result["attempts"]:
            self.assertEqual(attempt["status"], "complete")
            self.assertTrue((self.root / attempt["artifact_ref"]).is_file())
            self.assertLess(attempt["end"], "2023-01-03")
        directory = self.root / "daily-studies" / result["experiment_id"]
        events = [json.loads(line) for line in (directory / "attempts.jsonl").read_text().splitlines()]
        self.assertEqual(len(events), 48)
        self.assertEqual([event["event"] for event in events], ["started", "completed"] * 24)
        self.assertEqual(json.loads((self.output / "daily-study.json").read_text()), result)
        with closing(sqlite3.connect(self.root / "daily-studies.sqlite")) as database, database:
            status, snapshot = database.execute("SELECT status,protocol FROM studies WHERE id=?", (result["experiment_id"],)).fetchone()
        self.assertEqual(status, "complete")
        self.assertEqual(json.loads(snapshot), result)

    def test_failed_and_cancelled_attempts_keep_prior_results_and_terminal_events(self):
        for error in [RuntimeError("explicit fixture failure"), KeyboardInterrupt()]:
            calls = 0
            def interrupted(*args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 4:
                    raise error
                return self.simulate(*args, **kwargs)
            result, mocks = self.run_study(simulate=interrupted)
            expected = "cancelled" if isinstance(error, KeyboardInterrupt) else "failed"
            with self.subTest(expected=expected):
                self.assertEqual(result["status"], expected, result["errors"])
                self.assertEqual(len(result["attempts"]), 4)
                self.assertEqual([item["status"] for item in result["attempts"]], ["complete"] * 3 + [expected])
                self.assertFalse(result["attempts"][-1]["artifact_available"])
                self.assertEqual(mocks["report"].call_count, 0)
                directory = self.root / "daily-studies" / result["experiment_id"]
                events = [json.loads(line) for line in (directory / "attempts.jsonl").read_text().splitlines()]
                self.assertEqual([item["event"] for item in events], ["started", "completed"] * 3 + ["started", "terminated"])
                self.assertEqual(events[-1]["status"], expected)
                for attempt in result["attempts"][:-1]:
                    self.assertTrue((self.root / attempt["artifact_ref"]).is_file())
                self.assertEqual(json.loads((self.output / "daily-study.json").read_text()), result)

    def test_existing_attempt_lineage_increases_multiplicity_beyond_minimum_ten(self):
        self.root.mkdir()
        with closing(sqlite3.connect(self.root / "daily-studies.sqlite")) as database, database:
            database.execute("CREATE TABLE studies (id TEXT PRIMARY KEY, protocol TEXT, status TEXT)")
            prior = {"protocol_id": "old-declared-protocol", "candidate_grid": [{"configuration": number} for number in range(8)]}
            database.execute("INSERT INTO studies VALUES (?,?,?)", (uuid4().hex, json.dumps(prior), "failed"))
        result, mocks = self.run_study()
        self.assertEqual(result["status"], "complete", result["errors"])
        self.assertEqual(result["multiple_testing"]["correction_configurations"], 12)
        self.assertEqual({call.kwargs["configurations"] for call in mocks["evidence"].call_args_list}, {12})

    def test_exact_cached_dataset_reuses_provenance_without_provider_access(self):
        first, _ = self.run_study()
        second, mocks = self.run_study()
        self.assertEqual(second["status"], "complete", second["errors"])
        mocks["acquisition"].assert_not_called()
        mocks["loaded"].assert_called_once()
        self.assertEqual(second["dataset_id"], first["dataset_id"])
        self.assertEqual(second["provenance_ref"], first["provenance_ref"])
        self.assertFalse(second["reserved_final"]["accessed"])

    def test_cache_with_different_or_missing_adjustment_settings_is_not_reused(self):
        self.run_study()
        for key, value in [("auto_adjust", True), ("interval", "1wk"), ("repair", None)]:
            for path in (self.root / "daily-studies").glob("*/dataset/manifest.json"):
                manifest = deepcopy(self.manifest)
                if value is None:
                    manifest["request"].pop(key)
                else:
                    manifest["request"][key] = value
                path.write_text(json.dumps(manifest))
            result, mocks = self.run_study()
            with self.subTest(key=key, value=value):
                self.assertEqual(result["status"], "complete", result["errors"])
                mocks["acquisition"].assert_called_once()
                mocks["loaded"].assert_not_called()

    def test_provider_contract_never_requests_the_reserved_price_path(self):
        # A tiny explicit calendar isolates request construction from coverage arithmetic.
        sessions = MarketCalendar().sessions("2000-01-03", "2000-01-05")
        index = pd.DatetimeIndex([session.date for session in sessions], tz="America/New_York")
        frame = self.frames["XLB"].set_axis(index)
        calls = []
        class Calendar:
            def sessions(self, *_args): return sessions
        class Ticker:
            def __init__(self, symbol): self.symbol = symbol
            def history(self, **kwargs):
                calls.append((self.symbol, kwargs))
                return frame.copy()
            def get_history_metadata(self):
                return {"currency": "USD", "exchangeTimezoneName": "America/New_York"}
        _, manifest = acquire_daily_observations(SectorResearchSpec(), Path(self.temporary.name) / "capture",
                                                 ticker_factory=Ticker, calendar=Calendar())
        self.assertEqual([symbol for symbol, _ in calls], list(SECTOR_UNIVERSE))
        self.assertFalse(manifest["final_period_requested"])
        for symbol, request in calls:
            with self.subTest(symbol=symbol):
                self.assertEqual(request["start"], "2000-01-03")
                self.assertEqual(request["end"], "2022-12-31")
                self.assertEqual(request["interval"], "1d")
                self.assertFalse(request["auto_adjust"])
                self.assertFalse(request["back_adjust"])
                self.assertFalse(request["repair"])
                self.assertTrue(request["actions"])
                self.assertTrue(request["keepna"])
                self.assertTrue((Path(self.temporary.name) / "capture" / f"raw-{symbol}.json").is_file())

    def test_paired_evidence_rejects_equal_length_misaligned_dates(self):
        dates = pd.date_range("2018-01-31", periods=36, freq="ME")
        candidate = {"metrics": {"initial_equity": 100.0}, "rows": [
            {"date": day.date().isoformat(), "equity": 100.0 + number} for number, day in enumerate(dates)]}
        for mismatch in ["date", "order", "length"]:
            benchmark = deepcopy(candidate)
            if mismatch == "date":
                benchmark["rows"][0]["date"] = "2018-01-30"
            elif mismatch == "order":
                benchmark["rows"] = list(reversed(benchmark["rows"]))
            else:
                benchmark["rows"].pop()
            with self.subTest(mismatch=mismatch), self.assertRaisesRegex(ValueError, "identical chronological"):
                paired_evidence(candidate, benchmark, configurations=10)


if __name__ == "__main__":
    unittest.main()
