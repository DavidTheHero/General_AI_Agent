"""Known answers for weekly reversal timing, normalization and proxy accounting."""
from copy import deepcopy
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from pydantic import ValidationError

from trading_agent.calendar import MarketCalendar
from trading_agent.daily_screen import reconcile_daily_proxy
from trading_agent.weekly_screen import WEEKLY_UNIVERSE, WeeklyReversalPolicySpec, simulate_weekly_reversal


def fixture(start="2019-01-02", end="2020-05-05"):
    index = pd.DatetimeIndex([session.date for session in MarketCalendar().sessions(start, end)], tz="America/New_York")
    prices = 100 * np.exp(np.cumsum(np.where(np.arange(len(index)) % 2, .01, -.01)))
    return {symbol: pd.DataFrame({"Open": prices, "High": prices, "Low": prices, "Close": prices,
        "Adj Close": prices, "Volume": 1000000.0}, index=index) for symbol in WEEKLY_UNIVERSE}


def set_prices(frame, values):
    for column in ["Open", "High", "Low", "Close", "Adj Close"]:
        frame[column] = values


class WeeklySignalTests(unittest.TestCase):
    def test_frozen_contract_and_exact_universe(self):
        self.assertEqual(WeeklyReversalPolicySpec().lookback, 5)
        self.assertEqual(WeeklyReversalPolicySpec().holdings, 3)
        for update in [{"lookback": 2}, {"holdings": 2}, {"volatility_sessions": 62},
                       {"rebalance": "month_end"}, {"max_gross_weight": .9}, {"filter": "trend"}]:
            with self.subTest(update=update), self.assertRaises(ValidationError):
                WeeklyReversalPolicySpec.model_validate(update)
        frames = fixture()
        frames.pop("DBC")
        with self.assertRaisesRegex(ValueError, "exactly"):
            simulate_weekly_reversal(frames, {}, "2020-04-09", "2020-04-13")

    def test_known_answer_exact_lagged_volatility_and_normalized_ranking(self):
        for lookback in [1, 5]:
            frames = fixture()
            index = frames["SPY"].index
            t = index.get_loc(pd.Timestamp("2020-04-09", tz="America/New_York"))
            for symbol in WEEKLY_UNIVERSE:
                amplitude = .1 if symbol == "SPY" else .01
                returns = np.where(np.arange(len(index) - 1) % 2, amplitude, -amplitude)
                prices = np.r_[100.0, 100 * np.exp(np.cumsum(returns))]
                base = prices[t - lookback]
                move = {"SPY": -.1, "IWM": -.04, "QQQ": -.03, "EFA": -.02}.get(symbol, .02)
                prices[t - lookback + 1:t + 1] = base * np.exp(np.arange(1, lookback + 1) * move / lookback)
                if symbol == "IWM":
                    # This extreme adjacent close is outside the 64-close sigma window.
                    prices[t - lookback - 64] = .001
                    if lookback == 5:
                        # A large, recovered move inside the signal interval must also
                        # stay outside volatility; its final five-session return is unchanged.
                        prices[t - 4:t] = base * np.exp(np.linspace(-1, -.2, 4))
                set_prices(frames[symbol], prices)
            result = simulate_weekly_reversal(frames, {"lookback": lookback}, "2020-04-09", "2020-04-13", cost_bps=0)
            with self.subTest(lookback=lookback):
                self.assertEqual(result["decisions"][0]["weights"], {
                    symbol: 1 / 3 if symbol in {"IWM", "QQQ", "EFA"} else 0 for symbol in WEEKLY_UNIVERSE})
                # SPY has the largest raw loss, but much greater lagged volatility.
                self.assertNotIn("SPY", [fill["symbol"] for fill in result["fills"]])

    def test_ties_keep_declared_order_and_warmup_is_l_plus_64(self):
        frames = fixture()
        t = frames["SPY"].index.get_loc(pd.Timestamp("2020-04-09", tz="America/New_York"))
        for lookback in [1, 5]:
            minimum = {symbol: frame.iloc[t - lookback - 63:] for symbol, frame in reversed(list(frames.items()))}
            result = simulate_weekly_reversal(minimum, {"lookback": lookback}, "2020-04-09", "2020-04-13")
            with self.subTest(lookback=lookback):
                self.assertEqual(result["decisions"][0]["completed_observations"], lookback + 64)
                self.assertEqual([fill["symbol"] for fill in result["fills"]], list(WEEKLY_UNIVERSE[:3]))
                short = simulate_weekly_reversal({symbol: frame.iloc[1:] for symbol, frame in minimum.items()},
                    {"lookback": lookback}, "2020-04-09", "2020-04-13")
                self.assertEqual(short["fills"], [])
                self.assertIn("warm-up", short["decisions"][0]["reason"])

    def test_zero_volatility_fails_without_dropping_asset(self):
        frames = fixture()
        set_prices(frames["DBC"], 100.0)
        with self.assertRaisesRegex(ValueError, "positive lagged"):
            simulate_weekly_reversal(frames, {}, "2020-04-09", "2020-04-13")

    def test_host_rejects_malformed_proposals(self):
        base = {symbol: 0.0 for symbol in WEEKLY_UNIVERSE}
        invalid = [dict(base, SPY=-.1), dict(base, SPY=float("nan")), dict(base, SPY=.5),
                   {symbol: .2 for symbol in WEEKLY_UNIVERSE}, {"SPY": 1.0}, dict(base, SPY=True)]
        for target in invalid:
            with self.subTest(target=target), patch("trading_agent.weekly_screen._weekly_target", return_value=(target, "Invalid test proposal")), self.assertRaises((ValueError, ValidationError)):
                simulate_weekly_reversal(fixture(), {}, "2020-04-09", "2020-04-13")

    def test_reference_allocation_activates_at_next_open_across_year(self):
        frames = fixture("2015-01-02", "2017-01-10")
        weights = lambda symbol: {ticker: float(ticker == symbol) for ticker in WEEKLY_UNIVERSE}
        allocations = {"2015-01-02": weights("SPY"), "2017-01-03": weights("IEF")}
        result = simulate_weekly_reversal(frames, {"kind": "training_allocation"}, "2016-12-23", "2017-01-06",
            allocation_by_fold=allocations, cost_bps=0)
        decision = next(item for item in result["decisions"] if item["date"] == "2016-12-30")
        self.assertEqual(decision["weights"], weights("IEF"))
        self.assertEqual(decision["execute_date"], "2017-01-03")
        self.assertEqual(result["allocation_by_fold"], allocations)
        self.assertEqual(result["allocation_activation"], "next_session_open")
        self.assertTrue(reconcile_daily_proxy(result, frames)["ok"])
        for broken in [None, {}, {"2017-1-3": weights("SPY")}, {"2017-01-03": {"SPY": 1.0}}]:
            with self.subTest(broken=broken), self.assertRaises((ValueError, ValidationError)):
                simulate_weekly_reversal(frames, {"kind": "training_allocation"}, "2016-12-23", "2017-01-06", allocation_by_fold=broken)


class WeeklyExecutionTests(unittest.TestCase):
    def test_good_friday_and_normal_week_execute_next_official_open(self):
        frames = fixture()
        result = simulate_weekly_reversal(frames, {"kind": "equal_weight"}, "2020-04-08", "2020-04-20", cost_bps=0)
        self.assertEqual([item["date"] for item in result["decisions"]], ["2020-04-09", "2020-04-17"])
        self.assertEqual([item["execute_date"] for item in result["decisions"]], ["2020-04-13", "2020-04-20"])
        self.assertTrue(all(fill["date"] == "2020-04-13" for fill in result["fills"]))
        self.assertTrue(reconcile_daily_proxy(result, frames)["ok"])

    def test_known_cost_and_overnight_mark_no_terminal_exit(self):
        frames = fixture()
        for frame in frames.values():
            set_prices(frame, 100.0)
        frames["SPY"].loc["2020-04-13", ["Open", "High", "Low", "Close", "Adj Close"]] = [110, 121, 110, 121, 121]
        frames["SPY"].loc["2020-04-14", ["Open", "High", "Low", "Close", "Adj Close"]] = [121, 133.1, 121, 133.1, 133.1]
        result = simulate_weekly_reversal(frames, {"kind": "buy_hold"}, "2020-04-09", "2020-04-14", initial_cash=1000, cost_bps=100)
        self.assertEqual(len(result["fills"]), 1)
        self.assertAlmostEqual(result["fills"][0]["normalized_units"], 1000 / 111.1)
        self.assertAlmostEqual(result["metrics"]["final_equity"], 1000 / 111.1 * 133.1)
        self.assertAlmostEqual(result["metrics"]["total_cost"], 1000 / 101)
        self.assertGreater(result["rows"][-1]["normalized_units"]["SPY"], 0)
        self.assertTrue(reconcile_daily_proxy(result, frames)["ok"])

    def test_weekly_reconciler_detects_invalid_schedule_and_targets(self):
        frames = fixture()
        result = simulate_weekly_reversal(frames, {}, "2020-04-09", "2020-04-20")
        self.assertTrue(reconcile_daily_proxy(result, frames)["ok"])
        for change in ["same_close", "wrong_signal", "decision_close", "missing_decision", "overweight", "schedule"]:
            broken = deepcopy(result)
            if change == "same_close": broken["fills"][0]["timestamp"] = broken["decisions"][0]["timestamp"]
            elif change == "wrong_signal": broken["fills"][0]["signal_date"] = "2020-04-08"
            elif change == "decision_close": broken["decisions"][0]["date"] = "2020-04-08"
            elif change == "missing_decision": broken["decisions"].pop()
            elif change == "overweight": broken["decisions"][0]["weights"]["SPY"] = .5
            else: broken.pop("signal_schedule")
            with self.subTest(change=change):
                self.assertFalse(reconcile_daily_proxy(broken, frames)["ok"])

    def test_future_perturbation_prefix_replay_and_adjustment_scale(self):
        frames = fixture()
        complete = simulate_weekly_reversal(frames, {}, "2020-04-08", "2020-05-05")
        prefix = simulate_weekly_reversal(frames, {}, "2020-04-08", "2020-04-20")
        self.assertEqual(prefix["rows"], [row for row in complete["rows"] if row["date"] <= "2020-04-20"])
        altered = deepcopy(frames)
        for number, frame in enumerate(altered.values(), 2):
            future = frame.index >= pd.Timestamp("2020-04-21", tz="America/New_York")
            frame.loc[future, ["Open", "High", "Low", "Close", "Adj Close"]] *= number
        changed = simulate_weekly_reversal(altered, {}, "2020-04-08", "2020-05-05")
        self.assertEqual(prefix["rows"], [row for row in changed["rows"] if row["date"] <= "2020-04-20"])
        self.assertEqual(prefix["decisions"], [row for row in changed["decisions"] if row["date"] <= "2020-04-20"])
        frames["SPY"]["Adj Close"] *= .5
        scaled = simulate_weekly_reversal(frames, {}, "2020-04-08", "2020-05-05")
        self.assertEqual(complete["decisions"], scaled["decisions"])
        np.testing.assert_allclose([row["equity"] for row in complete["rows"]], [row["equity"] for row in scaled["rows"]])


if __name__ == "__main__":
    unittest.main()
