"""Research protocol known answers: selection boundaries, frozen holdouts and ledgers."""
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

import pandas as pd
from pydantic import ValidationError

from trading_agent.calendar import MarketCalendar, Session
from trading_agent.config import AgentConfig, StrategyConfig
from trading_agent.data import SyntheticFeed
from trading_agent.datasets import DatasetStore
from trading_agent.research import ExperimentSpec, ResearchJobRequest, compare_experiments, inspect_attempt, inspect_experiment, run_experiment


class Calendar:
    def __init__(self):
        self.values = [Session(session.date, session.open, session.open + pd.Timedelta(minutes=20))
                       for session in MarketCalendar().sessions("2026-10-01", "2026-10-08")]

    def sessions(self, start, end):
        return [session for session in self.values if start <= session.date <= end]


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.calendar = Calendar()
        self.request = {"source": "synthetic", "symbols": ["TEST"], "start": "2026-10-01", "end": "2026-10-08", "interval": "5m", "seed": 7}
        self.store = DatasetStore(self.root / "datasets")
        self.manifest = self.store.acquire(self.request, calendar=self.calendar)
        self.spec = ExperimentSpec(dataset_id=self.manifest["dataset_id"], config=AgentConfig(symbols=["TEST"], initial_cash=1000),
            candidates=[StrategyConfig(kind="trend_following", fast_window=1, slow_window=2), StrategyConfig(kind="mean_reversion", slow_window=2)],
            train_sessions=2, validation_sessions=1, final_sessions=2)

    def tearDown(self):
        for directory in self.root.rglob("*"):
            if directory.is_dir():
                directory.chmod(0o755)
        self.temporary.cleanup()

    def run_study(self, spec=None):
        experiment_id = uuid4().hex
        return run_experiment(spec or self.spec, self.root, self.root / "outputs" / experiment_id, experiment_id, calendar=self.calendar)

    def test_reproducible_validation_records_every_attempt_and_consistent_matched_metrics(self):
        first, second = self.run_study(), self.run_study()
        self.assertEqual(first["status"], "complete", first["errors"])
        self.assertEqual(second["status"], "complete", second["errors"])
        self.assertFalse(first["split"]["final_test_accessed"])
        final_dates = set(first["split"]["final_sessions"])
        for attempt in first["attempts"]:
            self.assertFalse(final_dates.intersection(attempt["sessions"]))
            self.assertTrue(attempt["reconciliation"]["ok"], attempt)
            self.assertIsNone(attempt["metrics"]["daily_sharpe_zero_risk_free"])
            evidence = inspect_attempt(self.root, first["experiment_id"], attempt["attempt_id"])
            self.assertEqual(evidence["attempt"], attempt)
            if attempt["period"] == "validation":
                benchmark = next(item for item in first["attempts"] if item["period"] == "validation_benchmark" and item["fold"] == attempt["fold"] and item["cost_multiplier"] == attempt["cost_multiplier"])
                self.assertEqual(attempt["metrics"]["benchmark_return_pct"], benchmark["metrics"]["return_pct"])
        self.assertEqual([item["metrics"] for item in first["attempts"]], [item["metrics"] for item in second["attempts"]])
        database = sqlite3.connect(self.root / "research.sqlite")
        self.assertEqual(database.execute("SELECT COUNT(*) FROM attempts WHERE experiment_id=?", (first["experiment_id"],)).fetchone()[0], len(first["attempts"]))
        for attempt_id, result in database.execute("SELECT id,result FROM attempts WHERE experiment_id=?", (first["experiment_id"],)):
            self.assertEqual(json.loads(result), next(item for item in first["attempts"] if item["attempt_id"] == attempt_id))
        database.close()
        self.assertTrue(compare_experiments(self.root, [first["experiment_id"], second["experiment_id"]])["comparable"])

    def test_final_test_requires_frozen_parent_and_is_consumed_once(self):
        parent = self.run_study()
        final_spec = self.spec.model_copy(update={"finalize": True, "parent_experiment_id": parent["experiment_id"]})
        final = self.run_study(final_spec)
        self.assertEqual(final["status"], "complete", final["errors"])
        self.assertTrue(final["split"]["final_test_accessed"])
        self.assertEqual(final["selected_strategy"], parent["selected_strategy"])
        self.assertEqual({item["period"] for item in final["attempts"]}, {"final", "final_benchmark"})
        self.assertTrue(all(item["strategy"] == parent["selected_strategy"] for item in final["attempts"] if item["period"] == "final"))
        repeated = self.run_study(final_spec)
        self.assertEqual(repeated["status"], "failed")
        self.assertIn("already been accessed", repeated["errors"][0])
        self.assertEqual(self.run_study()["status"], "failed")
        self.assertEqual(final["assessment"], "inconclusive")

    def test_reacquired_identical_observations_cannot_reset_holdout(self):
        parent = self.run_study()
        final = self.run_study(self.spec.model_copy(update={"finalize": True, "parent_experiment_id": parent["experiment_id"]}))
        self.assertEqual(final["status"], "complete")
        reacquired = self.store.acquire(self.request, calendar=self.calendar)
        self.assertNotEqual(reacquired["dataset_id"], self.manifest["dataset_id"])
        self.assertEqual(reacquired["observation_fingerprint"], self.manifest["observation_fingerprint"])
        self.assertEqual(self.run_study(self.spec.model_copy(update={"dataset_id": reacquired["dataset_id"]}))["status"], "failed")

    def test_changed_split_and_parent_protocol_fail_before_test_access(self):
        parent = self.run_study()
        wrong_parent = self.spec.model_copy(update={"train_sessions": 3, "finalize": True, "parent_experiment_id": parent["experiment_id"]})
        failed = self.run_study(wrong_parent)
        self.assertEqual(failed["status"], "failed")
        self.assertFalse(failed["split"]["final_test_accessed"])
        changed_final = self.run_study(self.spec.model_copy(update={"final_sessions": 3}))
        self.assertEqual(changed_final["status"], "failed")
        self.assertIn("different final period", changed_final["errors"][0])

    def test_final_environment_must_match_parent(self):
        parent = self.run_study()
        changed = {**parent["environment"], "python": "different"}
        with patch("trading_agent.research._environment", return_value=changed):
            result = self.run_study(self.spec.model_copy(update={"finalize": True, "parent_experiment_id": parent["experiment_id"]}))
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["split"]["final_test_accessed"])

    def test_future_final_observations_cannot_affect_development_selection(self):
        original = self.run_study()
        data, _ = self.store.load(self.manifest["dataset_id"])
        final_start = self.calendar.values[-2].open
        modified = data.frames["TEST"].copy()
        modified.loc[modified.index >= final_start, ["Open", "High", "Low", "Close"]] *= 100
        changed = self.store.save(replace(data, frames={"TEST": modified}), self.request, calendar=self.calendar)
        rerun = self.run_study(self.spec.model_copy(update={"dataset_id": changed["dataset_id"]}))
        self.assertEqual(original["selected_strategy"], rerun["selected_strategy"])
        self.assertEqual([item["metrics"] for item in original["attempts"]], [item["metrics"] for item in rerun["attempts"]])

    def test_failed_and_cancelled_attempts_preserve_open_evidence(self):
        from trading_agent.engine import IntradayAgent
        observe = IntradayAgent.observe
        calls = [0]

        def interrupted(agent, timestamp, bars):
            calls[0] += 1
            if calls[0] == 3:
                raise KeyboardInterrupt()
            return observe(agent, timestamp, bars)

        with patch.object(IntradayAgent, "observe", interrupted):
            result = self.run_study()
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["attempts"][0]["status"], "cancelled")
        evidence = inspect_attempt(self.root, result["experiment_id"], result["attempts"][0]["attempt_id"])
        self.assertFalse(evidence["sessions"][0]["finished"])
        self.assertTrue(evidence["reconciliations"][0]["ok"])
        self.assertEqual(inspect_experiment(self.root, result["experiment_id"])["status"], "cancelled")

    def test_invalid_requests_and_dataset_mismatch_are_explicit(self):
        for update in [{"cost_multipliers": [2.0, 1.0]}, {"finalize": True}, {"candidates": [self.spec.candidates[0]] * 2},
                       {"config": AgentConfig(costs={"commission_bps": 1000})}]:
            with self.assertRaises(ValidationError):
                ExperimentSpec.model_validate({**self.spec.model_dump(), **update})
        with self.assertRaises(ValidationError):
            ResearchJobRequest(mode="dataset", experiment=self.spec)
        mismatch = self.run_study(self.spec.model_copy(update={"config": AgentConfig(symbols=["OTHER"])}))
        self.assertEqual(mismatch["status"], "failed")
        self.assertIn("exactly match", mismatch["errors"][0])

    def test_cancellation_between_registration_and_processing_terminalizes_attempt(self):
        with patch("trading_agent.research._run_period", side_effect=KeyboardInterrupt()):
            result = self.run_study()
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["attempts"][0]["status"], "cancelled")
        self.assertFalse(result["attempts"][0]["artifact_available"])
        database = sqlite3.connect(self.root / "research.sqlite")
        self.assertEqual(database.execute("SELECT COUNT(*) FROM attempts WHERE status='running'").fetchone()[0], 0)
        database.close()

    def test_exhausted_capital_is_a_recorded_failure_without_zero_capital_replay(self):
        data, _ = self.store.load(self.manifest["dataset_id"])
        data.frames["TEST"].loc[:, ["Open", "High", "Low", "Close"]] = 5.0
        manifest = self.store.save(data, self.request, calendar=self.calendar)
        spec = self.spec.model_copy(update={"dataset_id": manifest["dataset_id"],
            "config": AgentConfig(symbols=["TEST"], initial_cash=10, costs={"fixed_fee": 5, "commission_bps": 0, "slippage_bps": 0}, risk={"max_position_weight": 1}),
            "candidates": [StrategyConfig(kind="buy_and_hold", target_gross_weight=1)]})
        result = self.run_study(spec)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["attempts"][0]["status"], "failed")
        self.assertEqual(result["attempts"][0]["metrics"]["final_equity"], 0)
        evidence = inspect_attempt(self.root, result["experiment_id"], result["attempts"][0]["attempt_id"])
        self.assertEqual(len(evidence["sessions"]), 1)
        self.assertTrue(evidence["reconciliations"][0]["ok"])


if __name__ == "__main__":
    unittest.main()
