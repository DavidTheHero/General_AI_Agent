"""Independent arithmetic and information-timing checks for the daily proxy pilot."""
from copy import deepcopy
import unittest

import numpy as np
import pandas as pd
from pydantic import ValidationError

from trading_agent.calendar import MarketCalendar
from trading_agent.daily_screen import DailyPolicySpec, reconcile_daily_proxy, simulate_daily, validate_daily_frames


def fixture(start="2020-06-01", end="2020-11-03"):
    dates = [session.date for session in MarketCalendar().sessions(start, end)]
    index = pd.DatetimeIndex(dates, tz="America/New_York")
    return {symbol: pd.DataFrame({"Open": 100.0, "High": 100.0, "Low": 100.0, "Close": 100.0,
                                 "Adj Close": 100.0, "Volume": 1000000.0, "Dividends": 0.0}, index=index)
            for symbol in ["SPY", "IEF", "GLD"]}


def price(frames, symbol, day, opening, closing):
    frames[symbol].loc[day, ["Open", "High", "Low", "Close", "Adj Close"]] = [
        opening, max(opening, closing), min(opening, closing), closing, closing]


class DailyDataTests(unittest.TestCase):
    def test_exact_coverage_and_invalid_data_are_reported(self):
        frames = fixture()
        dates = [session.date for session in MarketCalendar().sessions("2020-06-01", "2020-11-03")]
        self.assertTrue(validate_daily_frames(frames, dates)["usable"])
        for kind in ["gap", "duplicate", "nonfinite", "range", "adjustment", "unordered"]:
            broken = deepcopy(frames)
            if kind == "gap":
                broken["SPY"] = broken["SPY"].iloc[1:]
            elif kind == "duplicate":
                broken["SPY"] = pd.concat([broken["SPY"], broken["SPY"].iloc[-1:]])
            elif kind == "nonfinite":
                broken["SPY"].iloc[0, 0] = np.nan
            elif kind == "range":
                broken["SPY"].iloc[0, 1] = 99
            elif kind == "adjustment":
                broken["SPY"].iloc[0, 4] = 0
            else:
                broken["SPY"] = broken["SPY"].iloc[::-1]
            with self.subTest(kind=kind):
                self.assertFalse(validate_daily_frames(broken, dates)["usable"])
                with self.assertRaises(ValueError):
                    simulate_daily(broken, {"kind": "buy_hold"}, "2020-09-29", "2020-10-02")

    def test_policy_parameters_and_unrequested_universe_are_rejected(self):
        for config in [{"kind": "sma_cash", "lookback": 2}, {"kind": "relative_momentum", "rebalance": "daily"},
                       {"kind": "buy_hold", "max_gross_weight": 1.1}, {"kind": "unknown"}]:
            with self.subTest(config=config), self.assertRaises(ValidationError):
                DailyPolicySpec.model_validate(config)
        with self.assertRaises(ValueError):
            simulate_daily({"SPY": fixture()["SPY"]}, {"kind": "buy_hold"}, "2020-09-29", "2020-10-02")


class DailyExecutionTests(unittest.TestCase):
    def test_known_answer_next_open_and_overnight_carry(self):
        frames = fixture()
        price(frames, "SPY", "2020-10-01", 110, 121)
        price(frames, "SPY", "2020-10-02", 133.1, 140)
        result = simulate_daily(frames, {"kind": "buy_hold"}, "2020-09-29", "2020-10-02", initial_cash=1000, cost_bps=0)
        self.assertEqual(result["decisions"][0]["date"], "2020-09-30")
        self.assertEqual(result["fills"][0]["date"], "2020-10-01")
        self.assertEqual(result["fills"][0]["signal_date"], "2020-09-30")
        self.assertEqual([row["equity"] for row in result["rows"][:2]], [1000, 1000])
        self.assertAlmostEqual(result["rows"][2]["equity"], 1100)
        self.assertAlmostEqual(result["metrics"]["final_equity"], 1000 / 110 * 140)
        self.assertEqual(len(result["fills"]), 1)
        self.assertGreater(result["rows"][-1]["normalized_units"]["SPY"], 0)
        sessions = MarketCalendar().sessions("2020-09-29", "2020-10-02")
        years = (sessions[-1].close - sessions[0].open).total_seconds() / (86400 * 365.25)
        self.assertAlmostEqual(result["metrics"]["cagr_pct"], ((140 / 110) ** (1 / years) - 1) * 100, delta=result["metrics"]["cagr_pct"] * 1e-12)
        self.assertAlmostEqual(result["metrics"]["avg_exposure_pct"], 50)
        self.assertIsNone(result["metrics"]["annualized_volatility_pct"])

    def test_costs_reserve_cash_and_match_known_answer(self):
        result = simulate_daily(fixture(), {"kind": "buy_hold"}, "2020-09-30", "2020-10-02", initial_cash=1000, cost_bps=100)
        self.assertAlmostEqual(result["fills"][0]["normalized_units"], 1000 / 101)
        self.assertAlmostEqual(result["metrics"]["total_cost"], 1000 / 101)
        self.assertAlmostEqual(result["metrics"]["final_equity"], 100000 / 101)
        self.assertTrue(all(row["cash"] >= 0 for row in result["rows"]))
        stressed = simulate_daily(fixture(), {"kind": "buy_hold"}, "2020-09-30", "2020-10-02", initial_cash=1000, cost_bps=200)
        self.assertLess(stressed["metrics"]["final_equity"], result["metrics"]["final_equity"])

    def test_adjusted_dividend_does_not_create_extra_cash(self):
        frames = fixture()
        frames["SPY"]["Adj Close"] = 99.0
        price(frames, "SPY", "2020-10-02", 99, 99)
        frames["SPY"].loc["2020-10-02", "Dividends"] = 1.0
        result = simulate_daily(frames, {"kind": "buy_hold"}, "2020-09-30", "2020-10-02", initial_cash=1000, cost_bps=0)
        self.assertAlmostEqual(result["metrics"]["final_equity"], 1000)
        self.assertAlmostEqual(result["rows"][-1]["cash"], 0)
        self.assertEqual(result["fills"][0]["proxy_price"], 99)

    def test_sma_and_momentum_use_completed_warmup_and_month_end(self):
        frames = fixture()
        price(frames, "SPY", "2020-09-30", 100, 110)
        price(frames, "IEF", "2020-09-30", 100, 120)
        config = {"kind": "relative_momentum", "lookback": 63}
        result = simulate_daily(frames, config, "2020-09-29", "2020-10-02", cost_bps=0)
        self.assertEqual(result["decisions"][0]["weights"], {"SPY": 0, "IEF": 1, "GLD": 0})
        sma = simulate_daily(frames, {"kind": "sma_cash", "lookback": 63}, "2020-09-29", "2020-10-02", cost_bps=0)
        self.assertEqual(sma["decisions"][0]["weights"]["SPY"], 1)
        warmup = simulate_daily(fixture("2020-09-01"), config, "2020-09-29", "2020-10-02")
        self.assertEqual(warmup["fills"], [])

    def test_official_month_end_and_unexecuted_final_signal(self):
        result = simulate_daily(fixture(), {"kind": "equal_weight"}, "2020-10-29", "2020-10-30")
        # October 31 is Saturday; Friday's signal is known from the exchange calendar.
        self.assertEqual(result["decisions"][0]["date"], "2020-10-30")
        self.assertEqual(result["decisions"][0]["execute_date"], "2020-11-02")
        self.assertEqual(result["fills"], [])
        self.assertIsNotNone(result["pending_target"])

    def test_independent_ledger_reconciles_every_mark_and_sell_before_buy(self):
        frames = fixture()
        price(frames, "SPY", "2020-10-30", 100, 150)
        price(frames, "SPY", "2020-11-02", 150, 130)
        result = simulate_daily(frames, {"kind": "equal_weight", "max_gross_weight": 0.9}, "2020-09-29", "2020-11-03", initial_cash=1000, cost_bps=20)
        cash, holdings, applied = 1000.0, {symbol: 0.0 for symbol in frames}, 0
        for row in result["rows"]:
            for fill in result["fills"][applied:row["fill_count"]]:
                sign = 1 if fill["side"] == "buy" else -1
                cash -= sign * fill["normalized_units"] * fill["proxy_price"] + fill["cost"]
                holdings[fill["symbol"]] += sign * fill["normalized_units"]
                self.assertAlmostEqual(fill["cost"], fill["notional"] * 0.002)
                self.assertGreaterEqual(cash, -1e-10)
            applied = row["fill_count"]
            equity = cash + sum(holdings[symbol] * row["valuation_prices"][symbol] for symbol in frames)
            self.assertAlmostEqual(row["equity"], equity)
            self.assertAlmostEqual(row["cash"], cash)
            for symbol in holdings:
                self.assertAlmostEqual(row["normalized_units"][symbol], holdings[symbol])
        november = [fill["side"] for fill in result["fills"] if fill["date"] == "2020-11-02"]
        self.assertIn("sell", november)
        self.assertEqual(november[0], "sell")
        audit = reconcile_daily_proxy(result, frames)
        self.assertEqual(audit, {"ok": True, "errors": [], "rows_checked": len(result["rows"]), "fills_checked": len(result["fills"])})

    def test_independent_reconciler_detects_tampered_fills_marks_and_source(self):
        frames = fixture()
        result = simulate_daily(frames, {"kind": "buy_hold"}, "2020-09-29", "2020-10-02", initial_cash=1000, cost_bps=100)
        self.assertTrue(reconcile_daily_proxy(result, frames)["ok"])
        for key in ["proxy_price", "cost", "notional", "cash_after", "normalized_units"]:
            changed = deepcopy(result)
            changed["fills"][0][key] += 1
            with self.subTest(fill=key):
                self.assertFalse(reconcile_daily_proxy(changed, frames)["ok"])
        for key in ["cash", "equity", "cost", "cumulative_cost", "turnover", "fill_count"]:
            changed = deepcopy(result)
            changed["rows"][-1][key] += 1
            with self.subTest(mark=key):
                self.assertFalse(reconcile_daily_proxy(changed, frames)["ok"])
        changed = deepcopy(frames)
        changed["SPY"].loc["2020-10-01", "Open"] = 110
        self.assertFalse(reconcile_daily_proxy(result, changed)["ok"])
        changed = deepcopy(result)
        changed["rows"][0]["date"] = "2020-09-28"
        self.assertFalse(reconcile_daily_proxy(changed, frames)["ok"])

    def test_future_perturbation_replay_prefix_and_adjustment_scale_invariance(self):
        frames = fixture()
        price(frames, "SPY", "2020-09-30", 100, 110)
        config = {"kind": "sma_cash", "lookback": 63}
        complete = simulate_daily(frames, config, "2020-09-29", "2020-11-03")
        prefix = simulate_daily(frames, config, "2020-09-29", "2020-10-15")
        self.assertEqual(prefix["rows"], [row for row in complete["rows"] if row["date"] <= "2020-10-15"])
        self.assertEqual(prefix["decisions"], [row for row in complete["decisions"] if row["date"] <= "2020-10-15"])
        changed = deepcopy(frames)
        for symbol in changed:
            future = changed[symbol].index >= pd.Timestamp("2020-10-16", tz="America/New_York")
            changed[symbol].loc[future, ["Open", "High", "Low", "Close", "Adj Close"]] *= 7
        altered = simulate_daily(changed, config, "2020-09-29", "2020-11-03")
        self.assertEqual(prefix["rows"], [row for row in altered["rows"] if row["date"] <= "2020-10-15"])
        scaled = deepcopy(frames)
        scaled["SPY"]["Adj Close"] *= 0.5
        rescaled = simulate_daily(scaled, config, "2020-09-29", "2020-11-03")
        self.assertEqual(complete["decisions"], rescaled["decisions"])
        np.testing.assert_allclose([row["equity"] for row in complete["rows"]], [row["equity"] for row in rescaled["rows"]])


if __name__ == "__main__":
    unittest.main()
