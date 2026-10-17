"""Frozen weekly orchestration fixtures; engine arithmetic has independent tests."""
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
from trading_agent.daily_research import acquire_daily_observations
from trading_agent.datasets import checksum
from trading_agent.weekly_research import FOLDS, WeeklyResearchSpec, allocation_reference, fold_diagnostics, run_weekly_research
from trading_agent.weekly_reporting import write_weekly_report
from trading_agent.weekly_screen import WEEKLY_UNIVERSE


class WeeklyResearchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "research"
        self.output = Path(self.temporary.name) / "output"
        index = pd.DatetimeIndex(["2007-01-03", "2007-01-04", "2007-01-05"], tz="America/New_York")
        self.frames = {symbol: pd.DataFrame({"Open": 100.0, "High": 100.0, "Low": 100.0, "Close": 100.0,
                                             "Adj Close": 100.0, "Volume": 1000000.0}, index=index)
                       for symbol in WEEKLY_UNIVERSE}
        self.manifest = {"source": "explicit orchestration fixture; no strategy evidence", "dataset_id": "b" * 64,
            "request": {"symbols": list(WEEKLY_UNIVERSE), "start": "2007-01-03", "end_exclusive": "2022-12-31",
                        "interval": "1d", "auto_adjust": False, "back_adjust": False, "actions": True,
                        "repair": False, "keepna": True, "prepost": False, "rounding": False},
            "metadata": {symbol: {"fields": {"currency": "USD"}} for symbol in WEEKLY_UNIVERSE},
            "quality": {"usable": True, "warnings": ["Explicit fixture; no strategy evidence"]}}

    def acquire(self, spec, directory, **_kwargs):
        self.assertEqual(spec, WeeklyResearchSpec())
        # The source and exact declaration must precede any provider activity.
        self.assertTrue((directory.parent / "preregistered.json").is_file())
        self.assertTrue((directory.parent / "source" / "weekly_research.py").is_file())
        self.assertEqual((directory.parent / "declared-protocol.md").read_bytes(),
                         (Path(__file__).parents[2] / "docs" / "GLOBAL_REVERSAL_PROTOCOL.md").read_bytes())
        directory.mkdir()
        (directory / "manifest.json").write_text(json.dumps(self.manifest))
        return self.frames, self.manifest

    def simulate(self, frames, policy, start, end, *, cost_bps, initial_cash, allocation_by_fold=None):
        self.assertIs(frames, self.frames)
        self.assertLess(end, "2023-01-03")
        # Sensitivities deliberately win while the frozen primary loses.
        cagr = 6.0 if policy.kind == "weekly_reversal" and (policy.lookback, policy.holdings) == (5, 3) else 20.0 if policy.kind == "weekly_reversal" else 8.0
        dates = ["2008-01-11", "2010-06-04", "2012-12-28", "2014-12-26", "2016-12-30", "2018-12-28", "2020-12-24"]
        decisions = []
        for number, day in enumerate(dates):
            if start <= day <= end:
                selected = {WEEKLY_UNIVERSE[(number + offset) % len(WEEKLY_UNIVERSE)] for offset in range(3)}
                decisions.append({"date": day, "completed_observations": 500 + number,
                                  "weights": {symbol: 1 / 3 if symbol in selected else 0.0 for symbol in WEEKLY_UNIVERSE}})
        marks = [start, end]
        if start == "2013-01-02":
            marks = [day for first, last in FOLDS for day in [first, last]]
        rows = [{"date": day, "equity": initial_cash + (number + 1) * 1000,
                 "weights": {symbol: 1 / len(WEEKLY_UNIVERSE) for symbol in WEEKLY_UNIVERSE},
                 "cost": cost_bps, "turnover": .25, "drawdown_pct": 0.0} for number, day in enumerate(marks)]
        return {"policy": policy.model_dump(), "metrics": {"initial_equity": initial_cash, "cagr_pct": cagr,
                "final_equity": rows[-1]["equity"], "max_drawdown_pct": 10.0, "total_cost": cost_bps * len(rows)},
                "rows": rows, "fills": [], "decisions": decisions}

    def evidence(self, candidate, benchmark, *, configurations):
        return {"assessment": "promising_requires_replication" if candidate["metrics"]["cagr_pct"] > benchmark["metrics"]["cagr_pct"] else "rejects_alpha_claim",
                "family_configurations": configurations}

    def run_study(self, *, simulate=None, acquire=None, reconciliation=None):
        with patch("trading_agent.weekly_research.acquire_daily_observations", side_effect=acquire or self.acquire) as acquisition, \
             patch("trading_agent.weekly_research.load_daily", return_value=(self.frames, self.manifest)) as loaded, \
             patch("trading_agent.weekly_research.simulate_weekly_reversal", side_effect=simulate or self.simulate) as simulation, \
             patch("trading_agent.weekly_research.reconcile_daily_proxy", side_effect=reconciliation or (lambda *_args: {"ok": True, "errors": []})) as reconciled, \
             patch("trading_agent.weekly_research.paired_evidence", side_effect=self.evidence) as evidence, \
             patch("trading_agent.weekly_reporting.write_weekly_report") as report:
            record = run_weekly_research({}, self.root, self.output, uuid4().hex)
        return record, {"acquisition": acquisition, "loaded": loaded, "simulation": simulation,
                        "reconciliation": reconciled, "evidence": evidence, "report": report}

    def test_universe_dates_capital_costs_and_unknown_overrides_are_frozen(self):
        for update in [{"symbols": list(reversed(WEEKLY_UNIVERSE))}, {"symbols": list(WEEKLY_UNIVERSE[:-1])},
                       {"source": "stooq"}, {"data_start": "2006-01-03"}, {"development_start": "2009-01-02"},
                       {"validation_start": "2014-01-02"}, {"development_end": "2023-12-29"},
                       {"reserved_final_start": "2024-01-02"}, {"reserved_final_end": "2026-12-31"},
                       {"initial_cash": 99999.0}, {"cost_bps": [5.0, 20.0, 10.0]}, {"cost_bps": [5.0, 10.0, 30.0]},
                       {"lookback": 63}, {"finalize": True}]:
            with self.subTest(update=update), self.assertRaises(ValidationError):
                WeeklyResearchSpec.model_validate(update)

    def test_all_31_attempts_persist_with_fixed_primary_and_causal_reference_fits(self):
        result, mocks = self.run_study()
        self.assertEqual(result["status"], "complete", result["errors"])
        self.assertEqual(len(result["attempts"]), 31)
        self.assertEqual(mocks["simulation"].call_count, 31)
        self.assertEqual(mocks["reconciliation"].call_count, 31)
        self.assertEqual(len({item["attempt_id"] for item in result["attempts"]}), 31)
        for period, count in [("training_benchmark", 2), ("training", 4), ("allocation_training", 4),
                              ("validation", 12), ("validation_benchmark", 9)]:
            self.assertEqual(len([item for item in result["attempts"] if item["period"] == period]), count)
        self.assertEqual({(item["lookback"], item["holdings"]) for item in result["candidate_grid"]}, {(1, 1), (1, 3), (5, 1), (5, 3)})
        self.assertEqual((result["primary_policy"]["lookback"], result["primary_policy"]["holdings"]), (5, 3))
        self.assertEqual(result["assessment"], "rejects_alpha_claim")
        self.assertEqual(result["promotion_status"], "research_only")
        self.assertFalse(result["reserved_final"]["accessed"])
        self.assertEqual(len(result["comparisons"]), 24)
        self.assertEqual(len([item for item in result["comparisons"] if item["primary"]]), 6)
        self.assertEqual({item["benchmark"] for item in result["comparisons"]}, {"equal_weight", "training_allocation"})
        self.assertTrue(all(item["evidence"]["assessment"] == "promising_requires_replication" for item in result["comparisons"] if not item["primary"]))
        self.assertEqual(result["multiple_testing"]["correction_configurations"], 14)
        self.assertEqual({call.kwargs["configurations"] for call in mocks["evidence"].call_args_list}, {14})
        self.assertEqual(result["source_snapshot"], result["environment"]["source_sha256"])
        self.assertEqual([item["decisions"] for item in result["allocation_references"]], [3, 4, 5, 6, 7])
        for index, reference in enumerate(result["allocation_references"]):
            self.assertEqual(reference["fold_start"], FOLDS[index][0])
            self.assertLess(reference["latest_decision"], reference["fold_start"])
            self.assertLess(reference["training_end"], reference["fold_start"])
            self.assertEqual(set(reference["weights"]), set(WEEKLY_UNIVERSE))
            self.assertAlmostEqual(sum(reference["weights"].values()), 1)
        # The initial primary attempt is reused; no hidden 32nd training attempt.
        first_source = result["allocation_references"][0]["source_attempt_id"]
        self.assertEqual(next(item for item in result["attempts"] if item["attempt_id"] == first_source)["period"], "training")
        matched_calls = [call for call in mocks["simulation"].call_args_list if call.args[1].kind == "training_allocation"]
        self.assertEqual(len(matched_calls), 3)
        for call in matched_calls:
            self.assertEqual(call.args[2:4], ("2013-01-02", "2022-12-30"))
            self.assertEqual(call.kwargs["allocation_by_fold"], {item["fold_start"]: item["weights"] for item in result["allocation_references"]})
        for attempt in result["attempts"]:
            self.assertEqual(attempt["status"], "complete")
            self.assertTrue((self.root / attempt["artifact_ref"]).is_file())
            self.assertEqual(json.loads((self.root / attempt["artifact_ref"]).read_text())["attempt"], attempt)
            self.assertLess(attempt["end"], "2023-01-03")
            if attempt["period"].startswith("validation"):
                self.assertEqual(len(attempt["fold_diagnostics"]), 5)
                self.assertEqual(attempt["fold_diagnostics"][1]["starting_equity"], attempt["fold_diagnostics"][0]["ending_equity"])
        self.assertTrue(all("max_drawdown_pct" in item and "total_cost" in item for item in result["metrics"]["primary_validation_results"]))
        directory = self.root / "daily-studies" / result["experiment_id"]
        events = [json.loads(line) for line in (directory / "attempts.jsonl").read_text().splitlines()]
        self.assertEqual([event["event"] for event in events], ["started", "completed"] * 31)
        self.assertEqual(json.loads((self.output / "daily-study.json").read_text()), result)
        self.assertEqual(json.loads((self.output / "progress.json").read_text())["attempts_planned"], 31)
        declaration = json.loads((directory / "preregistered.json").read_text())
        self.assertEqual(declaration["declaration_sha256"], checksum(directory / "declared-protocol.md"))
        with closing(sqlite3.connect(self.root / "daily-studies.sqlite")) as database, database:
            status, snapshot = database.execute("SELECT status,protocol FROM studies WHERE id=?", (result["experiment_id"],)).fetchone()
        self.assertEqual(status, "complete")
        self.assertEqual(json.loads(snapshot), result)

    def test_reference_uses_target_mean_not_returns_fills_or_winner_and_rejects_future_targets(self):
        primary = type("Policy", (), {"kind": "weekly_reversal", "lookback": 5, "holdings": 3, "model_dump": lambda _: {}})()
        result = self.simulate(self.frames, primary, "2008-01-02", "2012-12-31", cost_bps=5, initial_cash=100000)
        fitted = allocation_reference(result, "2013-01-02", "2012-12-31", "prior-attempt")
        expected = {"SPY": 1 / 9, "IWM": 2 / 9, "QQQ": 1 / 3, "EFA": 2 / 9, "EEM": 1 / 9,
                    "IEF": 0.0, "TLT": 0.0, "GLD": 0.0, "DBC": 0.0}
        for symbol in WEEKLY_UNIVERSE:
            self.assertAlmostEqual(fitted["weights"][symbol], expected[symbol])
        changed = deepcopy(result)
        changed["metrics"]["cagr_pct"] = -99.0
        changed["fills"] = [{"symbol": "DBC", "notional": 9999999}]
        self.assertEqual(allocation_reference(changed, "2013-01-02", "2012-12-31", "prior-attempt"), fitted)
        for mutate in [lambda value: value["decisions"][-1].update(date="2013-01-02"),
                       lambda value: value["decisions"][-1].update(completed_observations=68),
                       lambda value: value["decisions"][-1]["weights"].update(SPY=float("nan")),
                       lambda value: value["decisions"][-1]["weights"].pop("DBC"),
                       lambda value: value["decisions"][-1]["weights"].update(SPY=-1.0)]:
            invalid = deepcopy(result)
            mutate(invalid)
            with self.assertRaises(ValueError):
                allocation_reference(invalid, "2013-01-02", "2012-12-31", "prior-attempt")

    def test_fold_metrics_slice_continuous_equity_and_count_boundary_costs_once(self):
        result = {"metrics": {"initial_equity": 100.0}, "rows": []}
        for index, (start, end) in enumerate(FOLDS):
            for offset, day in enumerate([start, end]):
                result["rows"].append({"date": day, "equity": 100 + (index * 2 + offset + 1) * 10,
                    "cost": 1.5, "turnover": .1, "weights": {symbol: .5 if symbol == "SPY" else 0.0 for symbol in WEEKLY_UNIVERSE}})
        folds = fold_diagnostics(result)
        self.assertEqual([item["starting_equity"] for item in folds], [100.0, 120.0, 140.0, 160.0, 180.0])
        self.assertAlmostEqual((1 + folds[0]["return_pct"] / 100) * (1 + folds[1]["return_pct"] / 100), 1.4)
        self.assertEqual(sum(item["total_cost"] for item in folds), 15.0)
        self.assertEqual([item["avg_exposure_pct"] for item in folds], [50.0] * 5)

    def test_failed_and_cancelled_attempts_keep_completed_results_and_terminal_events(self):
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
                self.assertEqual([item["status"] for item in result["attempts"]], ["complete"] * 3 + [expected])
                self.assertFalse(result["attempts"][-1]["artifact_available"])
                mocks["report"].assert_not_called()
                events = [json.loads(line) for line in (self.root / "daily-studies" / result["experiment_id"] / "attempts.jsonl").read_text().splitlines()]
                self.assertEqual([item["event"] for item in events], ["started", "completed"] * 3 + ["started", "terminated"])
                self.assertEqual(events[-1]["status"], expected)
                self.assertEqual(json.loads((self.output / "daily-study.json").read_text()), result)

    def test_ledger_failure_cannot_complete_or_publish_a_report(self):
        result, mocks = self.run_study(reconciliation=lambda *_args: {"ok": False, "errors": ["fixture independent cash mismatch"]})
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["attempts"][0]["status"], "failed")
        self.assertIn("independent cash mismatch", result["errors"][0])
        mocks["report"].assert_not_called()

    def test_provider_failure_keeps_request_source_and_no_invented_attempts(self):
        def unavailable(*_args, **_kwargs):
            raise ValueError("required ETF history unavailable")
        result, mocks = self.run_study(acquire=unavailable)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["attempts"], [])
        mocks["simulation"].assert_not_called()
        self.assertFalse(result["reserved_final"]["accessed"])
        self.assertTrue((self.root / "daily-studies" / result["experiment_id"] / "preregistered.json").is_file())

    def test_exact_cached_snapshot_reuses_original_provenance_without_provider_access(self):
        first, _ = self.run_study()
        second, mocks = self.run_study()
        self.assertEqual(second["status"], "complete", second["errors"])
        mocks["acquisition"].assert_not_called()
        mocks["loaded"].assert_called_once()
        self.assertEqual(second["dataset_id"], first["dataset_id"])
        self.assertEqual(second["provenance_ref"], first["provenance_ref"])

    def test_cache_different_dates_symbols_or_settings_is_not_silently_reused(self):
        self.run_study()
        for key, value in [("auto_adjust", True), ("interval", "1wk"), ("repair", None),
                           ("start", "2008-01-02"), ("end_exclusive", "2023-01-01"), ("symbols", list(reversed(WEEKLY_UNIVERSE)))]:
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

    def test_known_local_search_lineage_beyond_fourteen_is_retained(self):
        self.root.mkdir()
        with closing(sqlite3.connect(self.root / "daily-studies.sqlite")) as database, database:
            database.execute("CREATE TABLE studies (id TEXT PRIMARY KEY, protocol TEXT, status TEXT)")
            prior = {"protocol_id": "prior-hypothesis", "candidate_grid": [{"configuration": number} for number in range(15)]}
            database.execute("INSERT INTO studies VALUES (?,?,?)", (uuid4().hex, json.dumps(prior), "failed"))
        result, mocks = self.run_study()
        self.assertEqual(result["status"], "complete", result["errors"])
        self.assertEqual(result["multiple_testing"]["correction_configurations"], 19)
        self.assertEqual({call.kwargs["configurations"] for call in mocks["evidence"].call_args_list}, {19})

    def test_original_provider_contract_preserves_exact_scope_and_reserved_boundary(self):
        sessions = MarketCalendar().sessions("2007-01-03", "2007-01-05")
        calls = []
        frames = self.frames
        class Calendar:
            def sessions(self, *_args): return sessions
        class Ticker:
            def __init__(self, symbol): self.symbol = symbol
            def history(self, **kwargs):
                calls.append((self.symbol, kwargs))
                return frames[self.symbol].copy()
            def get_history_metadata(self):
                return {"currency": "USD", "exchangeTimezoneName": "America/New_York"}
        _, manifest = acquire_daily_observations(WeeklyResearchSpec(), Path(self.temporary.name) / "provider-contract",
                                                 ticker_factory=Ticker, calendar=Calendar())
        self.assertEqual([symbol for symbol, _ in calls], list(WEEKLY_UNIVERSE))
        self.assertFalse(manifest["final_period_requested"])
        for _, request in calls:
            self.assertEqual(request["start"], "2007-01-03")
            self.assertEqual(request["end"], "2022-12-31")
            self.assertEqual(request["interval"], "1d")
            for setting in ["auto_adjust", "back_adjust", "repair", "prepost", "rounding"]:
                self.assertFalse(request[setting])
            for setting in ["actions", "keepna"]:
                self.assertTrue(request[setting])

    def test_report_renders_actual_attempt_artifacts_without_promoting_sensitivity_winner(self):
        result, _ = self.run_study()
        write_weekly_report(result, self.root / "daily-studies" / result["experiment_id"], self.output)
        report = (self.output / "report.md").read_text(encoding="utf-8")
        self.assertIn("**rejects_alpha_claim**", report)
        self.assertIn("**research_only**", report)
        self.assertIn("Reserved 2023–2025 historical price paths were not requested", report)
        self.assertIn("| 5 / 3 | 6.00% | 10.00% | Primary |", report)
        self.assertIn("| 1 / 1 | 20.00% | 10.00% | Sensitivity; cannot replace primary |", report)
        self.assertIn("do not reset between validation folds", report)
        self.assertTrue((self.output / "performance.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))


if __name__ == "__main__":
    unittest.main()
