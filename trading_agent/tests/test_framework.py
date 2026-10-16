from dataclasses import replace
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
from pydantic import ValidationError

from trading_agent.calendar import MarketCalendar, Session
from trading_agent.config import AgentConfig, CostConfig, StrategyConfig
from trading_agent.data import DataError, MarketData, SyntheticFeed, YahooFinanceFeed, clean_bars, session_frames, validate_yahoo_window
from trading_agent.engine import IntradayAgent
from trading_agent.metrics import performance_metrics
from trading_agent.portfolio import Portfolio
from trading_agent.reporting import write_report
from trading_agent.runner import run_backtest, run_watch
from trading_agent.strategies import Decision, Observation, OllamaPolicy, RulePolicy


def short_session(date="2026-10-14"):
    return Session(date, pd.Timestamp(f"{date}T13:30:00Z"), pd.Timestamp(f"{date}T13:50:00Z"))


def config(**updates):
    base = {"symbols": ["TEST"], "initial_cash": 1000, "strategy": {"kind": "buy_and_hold", "target_gross_weight": 1},
            "risk": {"max_position_weight": 1}, "costs": {"commission_bps": 0, "slippage_bps": 0}, "data_lag_seconds": 0}
    base.update(updates)
    return AgentConfig.model_validate(base)


def frame(session=None, opens=None, closes=None):
    session = session or short_session()
    opens = opens or [100, 110, 130, 140]
    closes = closes or [100, 120, 135, 130]
    return pd.DataFrame({"Open": opens, "High": [max(a, b) + 1 for a, b in zip(opens, closes)],
                         "Low": [max(0.01, min(a, b) - 1) for a, b in zip(opens, closes)], "Close": closes, "Volume": 1000}, index=session.grid(5))


def market(frame_value=None):
    return MarketData({"TEST": frame_value if frame_value is not None else frame()}, "SYNTHETIC test fixture", "2026-10-15T00:00:00Z", {"TEST": {"currency": "USD"}})


class Clock:
    def __init__(self, now): self.now = pd.Timestamp(now)
    def __call__(self): return self.now
    def sleep(self, seconds): self.now += pd.Timedelta(seconds=seconds)


class CalendarFixture:
    def __init__(self, sessions): self.values = sessions
    def sessions(self, start, end): return [session for session in self.values if start <= session.date <= end]
    def upcoming(self, now): return next(session for session in self.values if session.close > now)


class FeedFixture:
    def __init__(self, data, failures=0): self.data, self.failures, self.calls = data, failures, 0
    def fetch(self, *args):
        self.calls += 1
        if self.calls <= self.failures: raise DataError("Temporary provider failure")
        return self.data


class ConfigurationAndCalendarTests(unittest.TestCase):
    def test_config_rejects_unsafe_or_mistyped_values(self):
        for values in [{"initial_cash": -1}, {"initial_cash": float("nan")}, {"symbols": ["SPY", "spy"]},
                       {"currency": "GBP"}, {"interval": "1d"}, {"unknown": True}, {"strategy": {"fast_window": 20, "slow_window": 10}},
                       {"risk": {"max_position_weight": 1.1}}, {"poll_seconds": 0}]:
            with self.subTest(values=values), self.assertRaises(ValidationError): AgentConfig.model_validate(values)
        self.assertEqual(AgentConfig(symbols=[" spy "]).symbols, ["SPY"])

    def test_calendar_holidays_dst_early_close_and_full_session(self):
        calendar = MarketCalendar()
        self.assertEqual(calendar.sessions("2026-07-03", "2026-07-05"), [])
        before = calendar.sessions("2026-03-06", "2026-03-06")[0]
        after = calendar.sessions("2026-03-09", "2026-03-09")[0]
        self.assertEqual(before.open.hour, 14); self.assertEqual(after.open.hour, 13)
        self.assertEqual(len(after.grid(5)), 78)
        early = calendar.sessions("2026-11-27", "2026-11-27")[0]
        self.assertEqual(early.close.tz_convert("America/New_York").hour, 13)
        self.assertEqual(len(early.grid(5)), 42)
        self.assertEqual(calendar.latest_completed(pd.Timestamp("2026-10-15T01:00Z")).date, "2026-10-14")


class DataTests(unittest.TestCase):
    def test_invalid_prices_duplicate_timestamps_and_naive_times_are_rejected(self):
        for kind in ["nan", "inconsistent", "duplicate", "naive"]:
            data = frame()
            if kind == "nan": data.iloc[0, 0] = float("nan")
            if kind == "inconsistent": data.iloc[0, 1] = 1
            if kind == "duplicate": data = pd.concat([data, data.iloc[:1]])
            if kind == "naive": data.index = data.index.tz_localize(None)
            with self.subTest(kind=kind), self.assertRaises(DataError): clean_bars(data)

    def test_missing_bars_are_not_filled_and_future_bars_are_not_exposed(self):
        session = short_session(); data = market()
        observed = session_frames(data, session, config(), complete_until=session.open + pd.Timedelta(minutes=7))
        self.assertEqual(len(observed["TEST"]), 1)
        data.frames["TEST"] = frame().drop(frame().index[1])
        with self.assertRaisesRegex(DataError, "No prices were filled"): session_frames(data, session, config())


    def test_uncompleted_invalid_bar_cannot_break_completed_bar_ingestion(self):
        data = market()
        data.frames["TEST"].iloc[-1, 0] = float("nan")
        selected = session_frames(data, short_session(), config(), complete_until="2026-10-14T13:36Z")
        self.assertEqual(len(selected["TEST"]), 1)

    def test_yahoo_adapter_preserves_unadjusted_prices_and_end_date_semantics(self):
        class Ticker:
            def history(self, **kwargs):
                self.kwargs = kwargs; return frame()
            def get_history_metadata(self): return {"currency": "USD", "exchangeName": "NMS", "exchangeTimezoneName": "America/New_York"}
        ticker = Ticker()
        data = YahooFinanceFeed(lambda _symbol: ticker, clock=lambda: pd.Timestamp("2026-10-15T20:00Z")).fetch(["TEST"], "2026-10-14", "2026-10-14", "5m")
        self.assertEqual(ticker.kwargs["end"], "2026-10-15")
        self.assertFalse(ticker.kwargs["auto_adjust"]); self.assertFalse(ticker.kwargs["prepost"])
        self.assertEqual(data.frames["TEST"].iloc[1].Open, 110)

    def test_mixed_currency_and_split_data_fail_explicitly(self):
        for currency, split in [("GBP", False), ("USD", True)]:
            class Ticker:
                def history(self, **_kwargs):
                    result = frame(); result["Stock Splits"] = [2 if split else 0, 0, 0, 0]; return result
                def get_history_metadata(self): return {"currency": currency}
            with self.assertRaises(DataError): YahooFinanceFeed(lambda _symbol: Ticker(), clock=lambda: pd.Timestamp("2026-10-15T20:00Z")).fetch(["TEST"], "2026-10-14", "2026-10-14", "5m")

    def test_expired_minute_request_is_rejected_before_contacting_yahoo(self):
        factory = unittest.mock.Mock()
        feed = YahooFinanceFeed(factory, clock=lambda: pd.Timestamp("2026-10-15T20:00Z"))
        with self.assertRaisesRegex(DataError, "recent 30 days"):
            feed.fetch(["AAPL"], "2026-01-01", "2026-10-01", "1m")
        factory.assert_not_called()

    def test_yahoo_window_allows_batches_but_enforces_retention_from_now(self):
        now = "2026-10-15T20:00Z"
        validate_yahoo_window("2026-10-07", "2026-10-14", "1m", now=now)
        validate_yahoo_window("2026-10-01", "2026-10-14", "1m", now=now)
        with self.assertRaisesRegex(DataError, "Splitting requests cannot recover expired data"):
            validate_yahoo_window("2026-01-01", "2026-01-02", "1m", now=now)
        with self.assertRaisesRegex(DataError, "recent 60 days"):
            validate_yahoo_window("2026-01-01", "2026-10-01", "5m", now=now)
        validate_yahoo_window("2026-01-01", "2026-10-01", "60m", now=now)
        with self.assertRaisesRegex(DataError, "recent 730 days"):
            validate_yahoo_window("2023-01-01", "2023-01-02", "60m", now=now)

    def test_minute_batches_merge_all_requested_bars_without_boundary_duplicates(self):
        sessions = MarketCalendar().sessions("2026-10-01", "2026-10-14")
        expected = SyntheticFeed(sessions).fetch(["TEST"], "2026-10-01", "2026-10-14", "1m").frames["TEST"]
        class Ticker:
            def __init__(self): self.calls = []
            def history(self, **kwargs):
                self.calls.append(kwargs)
                return expected.copy()  # Deliberate out-of-window overlap from a provider.
            def get_history_metadata(self): return {"currency": "USD", "exchangeName": "NMS", "exchangeTimezoneName": "America/New_York"}
        ticker = Ticker()
        data = YahooFinanceFeed(lambda _symbol: ticker, clock=lambda: pd.Timestamp("2026-10-15T20:00Z")).fetch(["TEST"], "2026-10-01", "2026-10-14", "1m")
        self.assertEqual([(call["start"], call["end"]) for call in ticker.calls], [("2026-10-01", "2026-10-08"), ("2026-10-08", "2026-10-15")])
        pd.testing.assert_frame_equal(data.frames["TEST"], expected.astype(float))
        self.assertFalse(data.frames["TEST"].index.has_duplicates)
        self.assertEqual(sum(item["rows"] for item in data.metadata["TEST"]["requests"]), len(expected))
        for session in sessions:
            self.assertEqual(len(session_frames(data, session, config(interval="1m"))["TEST"]), 390)

    def test_weekend_only_final_batch_is_empty_without_losing_prior_bars(self):
        sessions = MarketCalendar().sessions("2026-10-03", "2026-10-11")
        expected = SyntheticFeed(sessions).fetch(["TEST"], "2026-10-03", "2026-10-11", "1m").frames["TEST"]
        class Ticker:
            def history(self, start, end, **_kwargs):
                return expected.loc[(expected.index >= pd.Timestamp(start, tz="America/New_York")) & (expected.index < pd.Timestamp(end, tz="America/New_York"))].copy()
            def get_history_metadata(self): return {"currency": "USD"}
        data = YahooFinanceFeed(lambda _symbol: Ticker(), clock=lambda: pd.Timestamp("2026-10-15T20:00Z")).fetch(["TEST"], "2026-10-03", "2026-10-11", "1m")
        pd.testing.assert_frame_equal(data.frames["TEST"], expected.astype(float))
        self.assertEqual(data.metadata["TEST"]["requests"][-1]["rows"], 0)

    def test_failed_later_batch_does_not_return_a_shorter_dataset(self):
        class Ticker:
            calls = 0
            def history(self, **_kwargs):
                self.calls += 1
                if self.calls == 2: raise RuntimeError("Provider rate limit")
                return frame(short_session("2026-10-01"))
            def get_history_metadata(self): return {"currency": "USD"}
        ticker = Ticker()
        with self.assertRaisesRegex(DataError, "batch 2026-10-08 to 2026-10-15.*Provider rate limit"):
            YahooFinanceFeed(lambda _symbol: ticker, clock=lambda: pd.Timestamp("2026-10-15T20:00Z")).fetch(["TEST"], "2026-10-01", "2026-10-14", "1m")
        self.assertEqual(ticker.calls, 2)


class EngineTests(unittest.TestCase):
    def test_next_open_fills_no_future_history_and_scheduled_close_liquidation(self):
        counts = []
        class Policy:
            def decide(self, observation):
                counts.append(len(observation.history["TEST"]))
                self_case.assertLess(observation.history["TEST"].index.max(), observation.timestamp)
                observation.history["TEST"].iloc[0, 0] = 9999  # A policy cannot mutate host bars.
                return Decision(weights={"TEST": 1}, reason="Test allocation")
        self_case = self
        agent = IntradayAgent(config(), short_session(), policy=Policy())
        result = agent.replay({"TEST": frame()})
        self.assertEqual(counts, [1, 2, 3]); self.assertEqual(agent.history["TEST"].iloc[0].Open, 100)
        self.assertEqual(result["fills"][0]["reference_price"], 110)
        self.assertEqual(result["fills"][0]["quantity"], 9)
        self.assertEqual(result["fills"][0]["timestamp"], "2026-10-14T13:35:00+00:00")
        self.assertEqual(result["fills"][-1]["timestamp"], short_session().close.isoformat())
        self.assertEqual(result["final_equity"], 1180); self.assertEqual(result["holdings"]["TEST"]["quantity"], 0)
        self.assertGreater(result["equity"][-1]["bar_exposure"], 0)
        self.assertEqual(result["equity"][-1]["gross_exposure"], 0)

    def test_costs_cash_and_realized_pnl_reconcile(self):
        portfolio = Portfolio(1000, ["TEST"], CostConfig(commission_bps=100, slippage_bps=100))
        portfolio.rebalance("2026-10-14T13:30Z", {"TEST": 1}, {"TEST": 100}, "Allocation")
        self.assertEqual(portfolio.positions["TEST"].quantity, 9); self.assertGreaterEqual(portfolio.cash, 0)
        portfolio.liquidate("2026-10-14T20:00Z", {"TEST": 100}, "Close")
        self.assertAlmostEqual(portfolio.cash, 964)
        self.assertAlmostEqual(sum(fill.commission + fill.slippage_cost for fill in portfolio.fills), 36)
        self.assertAlmostEqual(sum(fill.realized_pnl for fill in portfolio.fills), -36)

    def test_unaffordable_exit_fee_does_not_corrupt_portfolio(self):
        portfolio = Portfolio(10, ["TEST"], CostConfig(fixed_fee=5, commission_bps=0, slippage_bps=0))
        portfolio.fill("2026-10-14T13:30Z", "TEST", "buy", 1, 5, "Open")
        with self.assertRaisesRegex(ValueError, "exit fees"): portfolio.liquidate("2026-10-14T20:00Z", {"TEST": 1}, "Close")
        self.assertEqual(portfolio.positions["TEST"].quantity, 1); self.assertEqual(portfolio.cash, 0)


    def test_execution_failure_marks_the_known_price_and_keeps_ledgers_consistent(self):
        c = config(initial_cash=10, costs={"fixed_fee": 5, "commission_bps": 0, "slippage_bps": 0}, risk={"max_position_weight": 1, "daily_loss_limit": 1})
        agent = IntradayAgent(c, short_session())
        prices = frame(opens=[5, 5, 5, 1], closes=[5, 5, 1, 1])
        with self.assertRaisesRegex(ValueError, "exit fees"):
            agent.replay({"TEST": prices})
        result = agent.result()
        self.assertEqual(result["status"], "execution_error"); self.assertFalse(result["finished"])
        self.assertEqual(result["final_equity"], result["equity"][-1]["equity"])
        self.assertEqual(result["holdings"]["TEST"]["market_price"], 1)
        self.assertEqual(result["holdings"]["TEST"]["quantity"], 1)
        self.assertEqual(performance_metrics([result], 10)["final_equity"], result["final_equity"])

    def test_boolean_allocations_are_not_numeric_weights(self):
        with self.assertRaises(ValidationError): Decision(weights={"TEST": True}, reason="Invalid type")

    def test_risk_caps_and_gross_limit_are_applied(self):
        c = config(strategy={"kind": "buy_and_hold", "target_gross_weight": 0.3}, risk={"max_position_weight": 0.5})
        agent = IntradayAgent(c, short_session())
        agent.observe(frame().index[0], {"TEST": frame().iloc[0].to_dict()})
        self.assertEqual(agent.decisions[0]["accepted_weights"], {"TEST": 0.3})

    def test_loss_stop_latches_and_liquidates_at_next_open(self):
        agent = IntradayAgent(config(), short_session())
        result = agent.replay({"TEST": frame(opens=[100, 100, 70, 90], closes=[100, 80, 90, 110])})
        self.assertEqual(result["halt_reason"], "daily_loss_limit")
        self.assertEqual(result["fills"][1]["reference_price"], 70)
        self.assertEqual(result["final_equity"], 700)
        self.assertEqual(sum(fill["side"] == "buy" for fill in result["fills"]), 1)

    def test_invalid_decisions_halt_instead_of_placing_unknown_or_leveraged_orders(self):
        for weights in [{"WRONG": 1}, {"TEST": -1}, {"TEST": 1.5}]:
            class Policy:
                calls = 0
                def decide(self, _observation):
                    self.calls += 1; return Decision(weights=weights, reason="Invalid allocation")
            policy = Policy()
            agent = IntradayAgent(config(risk={"max_consecutive_decision_errors": 2}), short_session(), policy=policy)
            result = agent.replay({"TEST": frame()})
            self.assertEqual(policy.calls, 2); self.assertEqual(result["status"], "policy_halted"); self.assertEqual(result["fills"], [])

    def test_repeated_polls_cannot_duplicate_decisions_or_fills(self):
        agent = IntradayAgent(config(), short_session())
        for timestamp, row in frame().iterrows():
            agent.observe(timestamp, {"TEST": row.to_dict()})
            if not agent.finished: self.assertFalse(agent.observe(timestamp, {"TEST": row.to_dict()}))
        self.assertEqual(len(agent.decisions), 3); self.assertEqual(len(agent.portfolio.fills), 2)

    def test_out_of_order_or_missing_events_fail_instead_of_skipping_a_bar(self):
        agent = IntradayAgent(config(), short_session())
        with self.assertRaises(ValueError): agent.observe(frame().index[1], {"TEST": frame().iloc[1].to_dict()})

    def test_rule_policy_waits_for_warmup(self):
        policy = RulePolicy(StrategyConfig(kind="sma", fast_window=1, slow_window=3))
        for n, expected in [(1, 0), (2, 0), (3, 0.9)]:
            self.assertEqual(policy.decide(Observation(frame().index[n - 1], {"TEST": frame().iloc[:n]}, {})).weights["TEST"], expected)


    def test_model_context_has_a_global_bar_budget_and_full_window_statistics(self):
        captured = []
        def transport(payload):
            captured.append(json.loads(payload["messages"][1]["content"]))
            return {"message": {"content": json.dumps({"weights": {f"T{i}": 0 for i in range(10)}, "reason": "Cash allocation"})}}
        policy = OllamaPolicy(StrategyConfig(kind="ollama", slow_window=500), transport)
        history = {f"T{i}": pd.concat([frame()] * 25, ignore_index=True).set_axis(pd.date_range("2026-10-14T13:30Z", periods=100, freq="min")) for i in range(10)}
        policy.decide(Observation(pd.Timestamp("2026-10-14T15:10Z"), history, {"cash": 1000}))
        self.assertEqual(sum(len(rows) for rows in captured[0]["bars"].values()), 60)
        self.assertEqual(captured[0]["window_features"]["T0"]["window_bars"], 100)
        self.assertEqual(captured[0]["window_features"]["T0"]["latest_close"], 130)

    def test_ollama_is_structured_and_receives_only_provided_evidence(self):
        payloads = []
        def transport(payload):
            payloads.append(payload); return {"message": {"content": json.dumps({"weights": {"TEST": 0.25}, "reason": "Limited positive trend evidence"})}}
        policy = OllamaPolicy(StrategyConfig(kind="ollama"), transport)
        decision = policy.decide(Observation(frame().index[1], {"TEST": frame().iloc[:1]}, {"cash": 1000}))
        self.assertEqual(decision.weights, {"TEST": 0.25})
        self.assertEqual(payloads[0]["format"]["properties"]["weights"]["required"], ["TEST"])
        evidence = json.loads(payloads[0]["messages"][1]["content"])
        self.assertEqual(len(evidence["bars"]["TEST"]), 1)
        self.assertFalse(payloads[0]["stream"])


class MetricsAndRunnerTests(unittest.TestCase):
    def test_metrics_use_initial_equity_costs_and_unavailable_short_sample_sharpe(self):
        result = IntradayAgent(config(), short_session()).replay({"TEST": frame()})
        metrics = performance_metrics([result], 1000)
        self.assertAlmostEqual(metrics["return_pct"], 18)
        self.assertEqual(metrics["closed_fill_win_rate_pct"], 100)
        self.assertIsNone(metrics["daily_sharpe_zero_risk_free"])
        self.assertIsNone(metrics["profit_factor"])
        self.assertAlmostEqual(metrics["gross_turnover"], (9 * 110 + 9 * 130) / 1000)
        self.assertGreater(metrics["average_exposure_pct"], 50)

    def test_backtest_carries_cash_generates_reports_and_preserves_reproducible_ledgers(self):
        sessions = [short_session(), short_session("2026-10-15")]
        combined = pd.concat([frame(session) for session in sessions])
        with tempfile.TemporaryDirectory() as output:
            record = run_backtest(config(), sessions[0].date, sessions[-1].date, output, calendar=CalendarFixture(sessions), feed=FeedFixture(market(combined)), now="2026-10-16T00:00Z")
            self.assertEqual(record["status"], "complete"); self.assertEqual(record["metrics"]["completed_sessions"], 2)
            self.assertEqual(record["sessions"][1]["initial_equity"], record["sessions"][0]["final_equity"])
            self.assertIsNotNone(record["metrics"]["daily_sharpe_zero_risk_free"])
            for name in ["report.html", "report.json", "report.md", "performance.png", "executions.png", "daily_pnl.png", "equity.csv", "fills.csv", "decisions.json", "2026-10-14/report.html", "2026-10-15/report.html"]:
                self.assertTrue((Path(output) / name).is_file(), name)
            saved = json.loads((Path(output) / "report.json").read_text())
            self.assertEqual(saved["metrics"], record["metrics"])
            self.assertTrue(all(position["quantity"] == 0 for session in saved["sessions"] for position in session["holdings"].values()))

    def test_no_data_is_reported_as_unavailable_not_a_zero_return(self):
        with tempfile.TemporaryDirectory() as output:
            record = run_backtest(config(), "2026-10-14", "2026-10-14", output, calendar=CalendarFixture([short_session()]), feed=FeedFixture(market(), failures=10), now="2026-10-15T00:00Z")
            self.assertEqual(record["status"], "partial"); self.assertIsNone(record["metrics"]["return_pct"])
            self.assertTrue(record["errors"]); self.assertTrue((Path(output) / "report.html").exists())

    def test_watch_ignores_future_bars_deduplicates_polls_and_finishes_automatically(self):
        clock = Clock("2026-10-14T13:29:00Z")
        feed = FeedFixture(market(), failures=1)
        with tempfile.TemporaryDirectory() as output:
            record = run_watch(config(), output, feed=feed, calendar=CalendarFixture([short_session()]), clock=clock, sleep=clock.sleep)
            self.assertEqual(record["status"], "complete"); self.assertEqual(record["metrics"]["fills"], 2)
            self.assertEqual(len(record["sessions"][0]["decisions"]), 3)
            self.assertGreater(feed.calls, 4)
            self.assertEqual(record["sessions"][0]["equity"][-1]["timestamp"], short_session().close.isoformat())
            self.assertTrue((Path(output) / "progress.json").exists())
            self.assertTrue(any("error" in source for source in record["provenance"]))


    def test_watch_applies_source_lag_and_does_not_finish_before_closing_data(self):
        clock = Clock("2026-10-14T13:30:00Z")
        calls = []
        class Feed:
            def fetch(self, *_args): calls.append(clock()); return market()
        with tempfile.TemporaryDirectory() as output:
            record = run_watch(config(data_lag_seconds=900), output, feed=Feed(), calendar=CalendarFixture([short_session()]), clock=clock, sleep=clock.sleep)
            self.assertEqual(record["status"], "complete")
            self.assertGreaterEqual(calls[0], pd.Timestamp("2026-10-14T13:50Z"))
            self.assertGreaterEqual(clock(), pd.Timestamp("2026-10-14T14:05Z"))

    def test_continuous_watch_carries_cash_across_sessions_until_interrupted(self):
        sessions = [short_session(day) for day in ["2026-10-14", "2026-10-15", "2026-10-16"]]
        class StoppingClock(Clock):
            def sleep(self, seconds):
                super().sleep(seconds)
                if self.now >= sessions[-1].open:
                    raise KeyboardInterrupt()
        clock = StoppingClock(sessions[0].open)
        data = market(pd.concat([frame(session) for session in sessions[:2]]))
        with tempfile.TemporaryDirectory() as output:
            record = run_watch(config(poll_seconds=300), output, session_count=None, calendar=CalendarFixture(sessions), feed=FeedFixture(data), clock=clock, sleep=clock.sleep)
            self.assertEqual(record["metrics"]["completed_sessions"], 2)
            self.assertEqual(record["sessions"][1]["initial_equity"], record["sessions"][0]["final_equity"])
            self.assertTrue(any("interrupted" in error for error in record["errors"]))
            self.assertEqual(record["status"], "partial")
            self.assertEqual(json.loads((Path(output) / "summary.json").read_text())["metrics"], record["metrics"])

    def test_interrupted_replay_keeps_the_actual_open_position(self):
        class Policy:
            calls = 0
            def decide(self, _observation):
                self.calls += 1
                if self.calls == 2: raise KeyboardInterrupt()
                return Decision(weights={"TEST": 1}, reason="Initial allocation")
        with tempfile.TemporaryDirectory() as output:
            record = run_backtest(config(), "2026-10-14", "2026-10-14", output, calendar=CalendarFixture([short_session()]), feed=FeedFixture(market()), now="2026-10-15T00:00Z", policy_factory=Policy)
            self.assertEqual(record["status"], "partial")
            self.assertEqual(record["sessions"][0]["holdings"]["TEST"]["quantity"], 9)
            self.assertFalse(record["sessions"][0]["finished"])
            self.assertEqual(len(record["sessions"][0]["fills"]), 1)
            self.assertEqual(record["sessions"][0]["final_equity"], 1090)
            self.assertEqual(record["metrics"]["final_equity"], 1090)


    def test_full_nyse_day_polling_matches_chronological_replay(self):
        session = MarketCalendar().sessions("2026-10-14", "2026-10-14")[0]
        c = config(poll_seconds=300, data_lag_seconds=900)
        data = SyntheticFeed([session]).fetch(c.symbols, session.date, session.date, c.interval)
        expected = IntradayAgent(c, session).replay(session_frames(data, session, c))
        clock = Clock(session.open - pd.Timedelta(minutes=1))
        with tempfile.TemporaryDirectory() as output:
            record = run_watch(c, output, feed=FeedFixture(data), calendar=CalendarFixture([session]), clock=clock, sleep=clock.sleep)
            self.assertEqual(record["status"], "complete")
            self.assertEqual(len(record["sessions"][0]["equity"]), 79)
            self.assertEqual(record["sessions"][0]["fills"], expected["fills"])
            self.assertEqual(record["metrics"]["final_equity"], expected["final_equity"])
            self.assertEqual(record["sessions"][0]["valuation_timestamp"], session.close.isoformat())

    def test_watch_provider_failure_limit_produces_a_partial_report(self):
        clock = Clock("2026-10-14T13:35:00Z")
        with tempfile.TemporaryDirectory() as output:
            record = run_watch(config(), output, feed=FeedFixture(market(), failures=10), calendar=CalendarFixture([short_session()]), clock=clock, sleep=clock.sleep)
            self.assertEqual(record["status"], "partial"); self.assertIn("failure limit", record["errors"][0])
            self.assertIsNone(record["metrics"]["final_equity"])

    def test_report_escapes_provider_text(self):
        with tempfile.TemporaryDirectory() as output:
            write_report(output, config(), [], mode="test", source="SYNTHETIC <script>bad()</script>", errors=["<script>bad()</script>"])
            html = (Path(output) / "report.html").read_text()
            self.assertNotIn("<script>bad()", html); self.assertIn("&lt;script&gt;", html)


if __name__ == "__main__":
    unittest.main()
