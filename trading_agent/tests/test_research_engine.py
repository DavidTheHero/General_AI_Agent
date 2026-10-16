"""Known answers and generated invariants for the shared research execution path."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from pydantic import ValidationError

from trading_agent.calendar import Session
from trading_agent.config import AgentConfig, StrategyConfig
from trading_agent.engine import IntradayAgent
from trading_agent.data import DataError, MarketData
from trading_agent.datasets import checksum, frame_record
from trading_agent.reconciliation import reconcile_session
from trading_agent.registry import list_strategies, validate_strategy
from trading_agent.runner import run_backtest, run_watch
from trading_agent.strategies import Decision, Observation, OllamaPolicy, RulePolicy


def fixture(closes=(100, 120, 135, 130), opens=(100, 110, 130, 140)):
    index = pd.date_range("2026-10-14T13:30Z", periods=len(closes), freq="5min")
    return pd.DataFrame({"Open": opens, "High": np.maximum(opens, closes) + 1,
                         "Low": np.maximum(0.01, np.minimum(opens, closes) - 1), "Close": closes, "Volume": 1000.0}, index=index).astype(float)


def session(frame):
    return Session("2026-10-14", frame.index[0], frame.index[-1] + pd.Timedelta(minutes=5))


def config(**updates):
    values = {"symbols": ["TEST"], "initial_cash": 1000.0,
              "strategy": {"kind": "buy_and_hold", "target_gross_weight": 1.0},
              "risk": {"max_position_weight": 1.0, "daily_loss_limit": 1.0},
              "costs": {"commission_bps": 0.0, "slippage_bps": 0.0}}
    values.update(updates)
    return AgentConfig.model_validate(values)


class RegistryAndPolicyTests(unittest.TestCase):
    def test_registry_is_versioned_and_discloses_limits(self):
        entries = {item["id"]: item for item in list_strategies()}
        self.assertEqual(set(entries), {"sma", "momentum", "buy_and_hold", "ollama", "trend_following", "mean_reversion", "opening_range_breakout"})
        for entry in entries.values():
            self.assertEqual(entry["version"], "1.0.0")
            for field in ["hypothesis", "parameters", "required_observations", "warmup", "failure_conditions", "prerequisites"]:
                self.assertTrue(entry[field])
        self.assertTrue(entries["ollama"]["experimental"])
        entries["sma"]["parameters"]["properties"]["slow_window"]["default"] = 999
        self.assertEqual(validate_strategy({"kind": "sma"})["config"]["slow_window"], 12)

    def test_invalid_versions_and_relevant_parameter_relationships_fail(self):
        for values in [{"kind": "trend_following", "version": "2.0.0"},
                       {"kind": "trend_following", "fast_window": 12, "slow_window": 12},
                       {"kind": "mean_reversion", "entry_z": 1.0, "exit_z": 1.0},
                       {"kind": "opening_range_breakout", "opening_range_bars": 0}]:
            with self.subTest(values=values), self.assertRaises(ValidationError):
                validate_strategy(values)

    def test_trend_warmup_and_legacy_sma_are_identical(self):
        data = fixture()
        trend = RulePolicy(StrategyConfig(kind="trend_following", fast_window=1, slow_window=3))
        legacy = RulePolicy(StrategyConfig(kind="sma", fast_window=1, slow_window=3))
        for count in range(1, len(data) + 1):
            observation = Observation(data.index[count - 1] + pd.Timedelta(minutes=5), {"TEST": data.iloc[:count]}, {})
            expected = 0.0 if count < 3 else 0.9
            self.assertEqual(trend.decide(observation).weights, {"TEST": expected})
            self.assertEqual(trend.decide(observation).weights, legacy.decide(observation).weights)

    def test_mean_reversion_entry_hysteresis_exit_and_zero_variance(self):
        policy = RulePolicy(StrategyConfig(kind="mean_reversion", slow_window=4, entry_z=1.5, exit_z=0.25))
        for closes, held, expected in [([100, 100, 100, 90], False, 0.9),
                                       ([100, 100, 90, 94], False, 0.0),
                                       ([100, 100, 90, 94], True, 0.9),
                                       ([100, 90, 94, 98], True, 0.0),
                                       ([100, 100, 100, 100], True, 0.0)]:
            data = fixture(closes, closes)
            observation = Observation(data.index[-1], {"TEST": data}, {"positions": {"TEST": {"quantity": 1 if held else 0}}})
            with self.subTest(closes=closes, held=held):
                self.assertEqual(policy.decide(observation).weights["TEST"], expected)

    def test_opening_range_is_fixed_and_breakout_latches(self):
        data = fixture([100, 100, 103, 95], [100, 100, 100, 103])
        policy = RulePolicy(StrategyConfig(kind="opening_range_breakout", opening_range_bars=2))
        for count, expected in [(1, 0), (2, 0), (3, 0.9), (4, 0.9)]:
            self.assertEqual(policy.decide(Observation(data.index[count - 1], {"TEST": data.iloc[:count]}, {})).weights["TEST"], expected)

    def test_ollama_request_and_response_are_in_decision_audit_even_when_invalid(self):
        for content in [json.dumps({"weights": {"TEST": 0.25}, "reason": "Evidence"}), "invalid JSON"]:
            policy = OllamaPolicy(StrategyConfig(kind="ollama"), lambda payload: {"model": "mutable-tag", "message": {"content": content}})
            data = fixture()
            agent = IntradayAgent(config(strategy={"kind": "ollama"}), session(data), policy=policy)
            agent.observe(data.index[0], {"TEST": data.iloc[0].to_dict()})
            audit = agent.decisions[0]["policy_audit"]
            self.assertFalse(audit["model_identity_verified"])
            self.assertIsNone(audit["model_digest"])
            self.assertEqual(audit["response"]["message"]["content"], content)
            evidence = json.loads(audit["request"]["messages"][1]["content"])
            self.assertEqual(len(evidence["bars"]["TEST"]), 1)


class ExecutionAndReconciliationTests(unittest.TestCase):
    def test_known_answer_independent_ledger_and_tamper_detection(self):
        data, settings = fixture(), config()
        result = IntradayAgent(settings, session(data)).replay({"TEST": data})
        answer = reconcile_session(result, settings)
        self.assertEqual(answer["errors"], [])
        self.assertEqual(answer["cash"], 1180)
        self.assertEqual(answer["realized_pnl"], 180)
        for field in ["commission", "fill_price", "reference_price", "realized_pnl", "quantity"]:
            changed = deepcopy(result)
            changed["fills"][0][field] += 1
            with self.subTest(field=field):
                self.assertFalse(reconcile_session(changed, settings)["ok"])
        changed = deepcopy(result)
        changed["equity"][2]["cash"] += 1
        self.assertFalse(reconcile_session(changed, settings)["ok"])

    def test_direct_observation_boundary_rejects_invalid_data_without_state_change(self):
        data = fixture()
        for field, value in [("Open", float("nan")), ("High", 1), ("Volume", -1), ("Close", True), ("Low", "99")]:
            agent = IntradayAgent(config(), session(data))
            bar = data.iloc[0].to_dict()
            bar[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                agent.observe(data.index[0], {"TEST": bar})
            self.assertFalse(agent.equity_rows)
            self.assertIsNone(agent.last_timestamp)
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            IntradayAgent(config(), session(data)).observe(data.index[0].tz_localize(None), {"TEST": data.iloc[0].to_dict()})

    def test_known_cost_answer_and_interrupted_open_holdings_reconcile(self):
        data = fixture([100, 100, 100, 100], [100, 100, 100, 100])
        settings = config(costs={"commission_bps": 100.0, "slippage_bps": 100.0})
        agent = IntradayAgent(settings, session(data))
        for timestamp, row in data.iloc[:2].iterrows():
            agent.observe(timestamp, {"TEST": row.to_dict()})
        partial = reconcile_session(agent.result(), settings)
        self.assertTrue(partial["ok"], partial["errors"])
        self.assertEqual(partial["quantities"], {"TEST": 9})
        for timestamp, row in data.iloc[2:].iterrows():
            agent.observe(timestamp, {"TEST": row.to_dict()})
        completed = reconcile_session(agent.result(), settings)
        self.assertTrue(completed["ok"], completed["errors"])
        self.assertAlmostEqual(completed["cash"], 964)
        self.assertAlmostEqual(completed["commission_cost"] + completed["slippage_cost"], 36)

    def test_failed_exit_reconciles_actual_holdings_and_known_marks(self):
        data = fixture([5, 5, 1, 1], [5, 5, 5, 1])
        settings = config(initial_cash=10.0, costs={"fixed_fee": 5.0, "commission_bps": 0.0, "slippage_bps": 0.0})
        class ExitPolicy:
            def decide(self, observation):
                return Decision(weights={"TEST": 1.0 if len(observation.history["TEST"]) < 3 else 0.0}, reason="Forced exit")
        agent = IntradayAgent(settings, session(data), policy=ExitPolicy())
        with self.assertRaisesRegex(ValueError, "exit fees"):
            agent.replay({"TEST": data})
        answer = reconcile_session(agent.result(), settings)
        self.assertTrue(answer["ok"], answer["errors"])
        self.assertEqual(answer["quantities"], {"TEST": 1})
        self.assertEqual(answer["final_equity"], 1)

    def test_identical_duplicates_are_idempotent_and_conflicts_fail_after_completion(self):
        data = fixture()
        agent = IntradayAgent(config(), session(data))
        agent.replay({"TEST": data})
        before = deepcopy(agent.result())
        for timestamp, row in data.iterrows():
            self.assertFalse(agent.observe(timestamp, {"TEST": row.to_dict()}))
        self.assertEqual(before, agent.result())
        bar = data.iloc[0].to_dict()
        bar["Volume"] += 1
        with self.assertRaisesRegex(ValueError, "Conflicting duplicate"):
            agent.observe(data.index[0], {"TEST": bar})

    def test_future_perturbation_cannot_change_past_decisions_or_fills(self):
        data = fixture([100, 98, 96, 100, 103, 105, 101, 108], [100, 100, 98, 96, 100, 103, 105, 101])
        changed = data.copy()
        changed.iloc[5:, :4] *= 1.5
        boundary = data.index[5]
        for kind in ["trend_following", "mean_reversion", "opening_range_breakout", "momentum", "buy_and_hold"]:
            settings = config(strategy={"kind": kind, "fast_window": 1, "slow_window": 3, "opening_range_bars": 2})
            original = IntradayAgent(settings, session(data)).replay({"TEST": data})
            perturbed = IntradayAgent(settings, session(data)).replay({"TEST": changed})
            with self.subTest(kind=kind):
                for key in ["decisions", "fills", "equity"]:
                    before = lambda row: pd.Timestamp(row["timestamp"]) < boundary if key == "fills" else pd.Timestamp(row["timestamp"]) <= boundary
                    self.assertEqual([row for row in original[key] if before(row)], [row for row in perturbed[key] if before(row)])

    def test_replay_equals_manual_continuous_stream_with_repeated_events(self):
        data, settings = fixture(), config(costs={"commission_bps": 2.0, "slippage_bps": 3.0, "fixed_fee": 0.5})
        expected = IntradayAgent(settings, session(data)).replay({"TEST": data})
        agent = IntradayAgent(settings, session(data))
        for timestamp, row in data.iterrows():
            agent.observe(timestamp, {"TEST": row.to_dict()})
            self.assertFalse(agent.observe(timestamp, {"TEST": row.to_dict()}))
        self.assertEqual(agent.result(), expected)
        self.assertTrue(reconcile_session(expected, settings)["ok"])

    def test_generated_long_only_ledgers_reconcile_under_costs_and_price_gaps(self):
        # Seeded generated sequences exercise cash, rounding, partial exits and caps.
        for seed in range(25):
            rng = np.random.default_rng(seed)
            opens = rng.uniform(20, 200, 16)
            closes = opens * rng.uniform(0.8, 1.2, 16)
            data = fixture(closes, opens)
            settings = config(initial_cash=float(rng.uniform(500, 10000)),
                              costs={"commission_bps": float(rng.uniform(0, 30)), "slippage_bps": float(rng.uniform(0, 50)), "fixed_fee": float(rng.uniform(0, 1))})
            class RandomTargets:
                def decide(self, observation):
                    return Decision(weights={"TEST": float(rng.uniform(0, 1))}, reason="Seeded allocation")
            result = IntradayAgent(settings, session(data), policy=RandomTargets()).replay({"TEST": data})
            answer = reconcile_session(result, settings)
            with self.subTest(seed=seed):
                self.assertTrue(answer["ok"], answer["errors"])
                self.assertGreaterEqual(answer["cash"], 0)
                self.assertEqual(answer["quantities"], {"TEST": 0})
                self.assertAlmostEqual(answer["cash"] - settings.initial_cash, answer["realized_pnl"])
                self.assertTrue(all(row["cash"] >= 0 for row in result["equity"]))

    def test_generated_multi_asset_allocations_share_cash_without_leverage(self):
        for seed in range(10):
            rng = np.random.default_rng(seed)
            opens = rng.uniform(20, 100, 12)
            data = fixture(opens * rng.uniform(0.9, 1.1, 12), opens)
            other = data.copy()
            other.loc[:, ["Open", "High", "Low", "Close"]] *= 1.3
            settings = config(symbols=["TEST", "OTHER"], risk={"max_position_weight": 0.6, "daily_loss_limit": 1.0},
                              costs={"commission_bps": 10.0, "slippage_bps": 20.0, "fixed_fee": 0.5})
            class RandomTargets:
                def decide(self, observation):
                    weights = rng.dirichlet([1, 1, 1])
                    return Decision(weights={"TEST": float(weights[0]), "OTHER": float(weights[1])}, reason="Seeded shared-capital allocation")
            result = IntradayAgent(settings, session(data), policy=RandomTargets()).replay({"TEST": data, "OTHER": other})
            answer = reconcile_session(result, settings)
            with self.subTest(seed=seed):
                self.assertTrue(answer["ok"], answer["errors"])
                self.assertTrue(all(row["cash"] >= 0 for row in result["equity"]))
                self.assertTrue(all(sum(row["accepted_weights"].values()) <= 1 for row in result["decisions"]))


class PollingIntegrityTests(unittest.TestCase):
    def run_polling(self, feed):
        data = fixture()
        class Clock:
            now = data.index[2]
            def __call__(self): return self.now
            def sleep(self, seconds): self.now += pd.Timedelta(seconds=seconds)
        class Calendar:
            def upcoming(self, now): return session(data)
        settings = config(data_lag_seconds=0.0, poll_seconds=60.0, max_data_errors=3)
        clock = Clock()
        with tempfile.TemporaryDirectory() as output:
            return run_watch(settings, output, feed=feed, calendar=Calendar(), clock=clock, sleep=clock.sleep), settings

    def test_polling_revised_processed_bar_fails_without_rewriting_ledger(self):
        class RevisedFeed:
            calls = 0
            def fetch(self, *args):
                self.calls += 1
                data = fixture()
                if self.calls > 1:
                    data.iloc[0, data.columns.get_loc("Volume")] += 1
                return MarketData({"TEST": data}, "SYNTHETIC revision fixture", "2026-10-14T13:40Z", {"TEST": {"currency": "USD"}})
        feed = RevisedFeed()
        record, settings = self.run_polling(feed)
        self.assertEqual(record["status"], "partial")
        self.assertTrue(any("Conflicting duplicate" in error for error in record["errors"]))
        self.assertEqual(feed.calls, 2)
        result = record["sessions"][0]
        self.assertEqual(result["holdings"]["TEST"]["quantity"], 9)
        self.assertEqual(result["final_equity"], 1090)
        self.assertTrue(reconcile_session(result, settings)["ok"])

    def test_stale_source_retries_then_preserves_actual_open_portfolio(self):
        class StaleFeed:
            def fetch(self, *args):
                return MarketData({"TEST": fixture().iloc[:2]}, "SYNTHETIC stale fixture", "2026-10-14T13:40Z", {"TEST": {"currency": "USD"}})
        record, settings = self.run_polling(StaleFeed())
        self.assertEqual(record["status"], "partial")
        self.assertTrue(any("data failure limit" in error and "missing" in error for error in record["errors"]))
        result = record["sessions"][0]
        self.assertEqual(len(result["decisions"]), 2)
        self.assertEqual(len(result["fills"]), 1)
        self.assertEqual(result["holdings"]["TEST"]["quantity"], 9)
        self.assertEqual(result["valuation_timestamp"], "2026-10-14T13:40:00+00:00")
        self.assertTrue(reconcile_session(result, settings)["ok"])

    def test_default_yahoo_archives_raw_response_and_failure_with_checksums(self):
        raw = fixture()
        raw["Dividends"], raw["Stock Splits"] = 0.0, 0.0
        class Calendar:
            def sessions(self, start, end): return [session(raw)]
        def feed(response_sink):
            class Feed:
                def fetch(self, symbols, start, end, interval):
                    request = {"start": start, "end": end, "interval": interval, "auto_adjust": False}
                    response_sink("TEST", request, raw, {"currency": "USD"}, None)
                    response_sink("TEST", request, None, {}, "Deliberate provider failure")
                    raise DataError("Deliberate provider failure")
            return Feed()
        with tempfile.TemporaryDirectory() as output, patch("trading_agent.runner.YahooFinanceFeed", side_effect=feed):
            record = run_backtest(config(), "2026-10-14", "2026-10-14", output, calendar=Calendar(), now="2026-10-15T00:00Z")
            self.assertEqual(record["status"], "partial")
            reference = record["provenance"][0]
            self.assertEqual(reference["raw_capture_ref"], "source-responses/index.jsonl")
            self.assertIn("not a validated", reference["archive_status"])
            index = [json.loads(line) for line in (Path(output) / reference["raw_capture_ref"]).read_text().splitlines()]
            self.assertEqual(len(index), 2)
            responses = []
            for item in index:
                path = Path(output) / "source-responses" / item["file"]
                self.assertEqual(checksum(path), item["sha256"])
                self.assertEqual(path.stat().st_mode & 0o222, 0)
                responses.append(json.loads(path.read_text()))
            self.assertEqual(responses[0]["frame"], frame_record(raw))
            self.assertEqual(responses[0]["request"]["interval"], "5m")
            self.assertEqual(responses[0]["request"]["start"], "2026-10-14")
            self.assertIsNone(responses[1]["frame"])
            self.assertEqual(responses[1]["error"], "Deliberate provider failure")


if __name__ == "__main__":
    unittest.main()
