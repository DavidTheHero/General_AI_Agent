"""Known-answer sector signals and independent shared-ledger checks."""
from copy import deepcopy
import unittest

import numpy as np
import pandas as pd
from pydantic import ValidationError

from trading_agent.calendar import MarketCalendar
from trading_agent.daily_screen import (
    SECTOR_SYMBOLS, SECTOR_UNIVERSE, SectorPolicySpec, reconcile_daily_proxy,
    simulate_daily, simulate_sector_daily,
)


def fixture(start="2019-01-02", end="2020-03-03"):
    index = pd.DatetimeIndex([session.date for session in MarketCalendar().sessions(start, end)],
                             tz="America/New_York")
    return {symbol: pd.DataFrame({"Open": 100.0, "High": 100.0, "Low": 100.0, "Close": 100.0,
                                 "Adj Close": 100.0, "Volume": 1000000.0}, index=index)
            for symbol in SECTOR_UNIVERSE}


def price(frames, symbol, index, value):
    frames[symbol].loc[index, ["Open", "High", "Low", "Close", "Adj Close"]] = value


class SectorSignalTests(unittest.TestCase):
    def test_frozen_parameters_and_exact_universe(self):
        self.assertEqual(SectorPolicySpec(kind="sector_momentum").model_dump(), {
            "kind": "sector_momentum", "lookback": 252, "holdings": 3, "skip_sessions": 21,
            "rebalance": "month_end", "max_gross_weight": 1.0,
        })
        for config in [{"lookback": 125}, {"holdings": 2}, {"skip_sessions": 20},
                       {"rebalance": "daily"}, {"max_gross_weight": 1.1}, {"filter": "positive"}]:
            with self.subTest(config=config), self.assertRaises(ValidationError):
                SectorPolicySpec.model_validate({"kind": "sector_momentum", **config})
        frames = fixture()
        for symbols in [SECTOR_SYMBOLS, (*SECTOR_UNIVERSE, "XLRE")]:
            altered = {symbol: frames.get(symbol, frames["XLB"]) for symbol in symbols}
            with self.subTest(symbols=symbols), self.assertRaises(ValueError):
                simulate_sector_daily(altered, {"kind": "sector_momentum"}, "2020-01-30", "2020-02-04")
        with self.assertRaises(ValueError):
            simulate_daily(frames, {"kind": "buy_hold"}, "2020-01-30", "2020-02-04")

    def test_known_answer_session_offsets_exclude_last_month_and_spy(self):
        for lookback in [126, 252]:
            frames = fixture()
            index = frames["XLB"].index
            signal = index.get_loc(pd.Timestamp("2020-01-31", tz="America/New_York"))
            denominator, numerator = index[signal - lookback], index[signal - 21]
            # XLB=80%, XLE=60%, XLF=40%; SPY would win if accidentally ranked.
            price(frames, "XLB", denominator, 50)
            price(frames, "XLB", numerator, 90)
            price(frames, "XLE", numerator, 160)
            price(frames, "XLF", numerator, 140)
            price(frames, "SPY", numerator, 10000)
            # Adjacent endpoints catch off-by-one errors; recent spikes are excluded.
            price(frames, "XLI", index[signal - lookback - 1], 1)
            price(frames, "XLK", index[signal - 22], 10000)
            for symbol in ["XLP", "XLU", "XLV", "XLY"]:
                price(frames, symbol, index[signal - 20:signal + 1], 1000)
            result = simulate_sector_daily(frames, {"kind": "sector_momentum", "lookback": lookback},
                                           "2020-01-30", "2020-02-04", cost_bps=0)
            expected = {symbol: 1 / 3 if symbol in {"XLB", "XLE", "XLF"} else 0.0 for symbol in SECTOR_UNIVERSE}
            with self.subTest(lookback=lookback):
                self.assertEqual(result["decisions"][0]["weights"], expected)
                self.assertEqual([fill["symbol"] for fill in result["fills"]], ["XLB", "XLE", "XLF"])
                self.assertTrue(all(fill["date"] == "2020-02-03" for fill in result["fills"]))

    def test_latest_21_closes_cannot_change_the_signal(self):
        frames = fixture()
        original = simulate_sector_daily(frames, {"kind": "sector_momentum"}, "2020-01-30", "2020-02-04")
        index = frames["XLB"].index
        signal = index.get_loc(pd.Timestamp("2020-01-31", tz="America/New_York"))
        for number, symbol in enumerate(SECTOR_UNIVERSE, 1):
            price(frames, symbol, index[signal - 20:signal + 1], 100.0 * number)
        changed = simulate_sector_daily(frames, {"kind": "sector_momentum"}, "2020-01-30", "2020-02-04")
        self.assertEqual(original["decisions"], changed["decisions"])

    def test_exact_l_plus_one_warmup_and_no_positive_return_filter(self):
        frames = fixture()
        index = frames["XLB"].index
        signal = index.get_loc(pd.Timestamp("2020-01-31", tz="America/New_York"))
        for symbol in SECTOR_SYMBOLS:
            price(frames, symbol, index[signal - 21], 90)
        frames = {symbol: frame.iloc[signal - 252:] for symbol, frame in reversed(list(frames.items()))}
        for holdings in [1, 3]:
            config = {"kind": "sector_momentum", "holdings": holdings}
            result = simulate_sector_daily(frames, config, "2020-01-31", "2020-02-03")
            with self.subTest(holdings=holdings):
                self.assertEqual(result["decisions"][0]["completed_observations"], 253)
                self.assertEqual(result["decisions"][0]["weights"], {
                    symbol: 1 / holdings if symbol in SECTOR_SYMBOLS[:holdings] else 0.0 for symbol in SECTOR_UNIVERSE})
                insufficient = {symbol: frame.iloc[1:] for symbol, frame in frames.items()}
                short = simulate_sector_daily(insufficient, config, "2020-01-31", "2020-02-03")
                self.assertEqual(short["decisions"][0]["completed_observations"], 252)
                self.assertEqual(short["fills"], [])

    def test_benchmarks_use_matching_entry_and_sector_only_basket(self):
        frames = fixture()
        basket = simulate_sector_daily(frames, {"kind": "sector_equal_weight"}, "2020-01-30", "2020-03-03")
        spy = simulate_sector_daily(frames, {"kind": "buy_hold"}, "2020-01-30", "2020-03-03")
        self.assertEqual(basket["decisions"][0]["weights"], {
            symbol: 1 / 9 if symbol != "SPY" else 0.0 for symbol in SECTOR_UNIVERSE})
        self.assertEqual(len(basket["decisions"]), 2)
        self.assertEqual(len(spy["decisions"]), 1)
        self.assertEqual(spy["decisions"][0]["weights"]["SPY"], 1)
        self.assertEqual({fill["symbol"] for fill in basket["fills"]}, set(SECTOR_SYMBOLS))
        self.assertEqual({fill["symbol"] for fill in spy["fills"]}, {"SPY"})
        self.assertEqual(basket["fills"][0]["date"], spy["fills"][0]["date"])
        self.assertEqual(spy["fills"][0]["date"], "2020-02-03")


class SectorExecutionTests(unittest.TestCase):
    def test_cost_known_answer_and_generic_reconciler_with_ten_frames(self):
        frames = fixture()
        for kind in ["sector_momentum", "sector_equal_weight", "buy_hold"]:
            config = {"kind": kind}
            result = simulate_sector_daily(frames, config, "2020-01-30", "2020-02-04",
                                           cost_bps=100, initial_cash=1000)
            with self.subTest(kind=kind):
                self.assertAlmostEqual(result["metrics"]["total_cost"], 1000 / 101)
                self.assertAlmostEqual(result["metrics"]["final_equity"], 100000 / 101)
                self.assertTrue(all(row["cash"] >= 0 for row in result["rows"]))
                self.assertTrue(reconcile_daily_proxy(result, frames)["ok"])
                stressed = simulate_sector_daily(frames, config, "2020-01-30", "2020-02-04",
                                                 cost_bps=200, initial_cash=1000)
                self.assertLess(stressed["metrics"]["final_equity"], result["metrics"]["final_equity"])
        price(frames, "XLB", "2020-02-28", 160)
        price(frames, "XLB", "2020-03-02", 120)
        rebalanced = simulate_sector_daily(frames, {"kind": "sector_equal_weight"}, "2020-01-30", "2020-03-03")
        self.assertEqual([fill["side"] for fill in rebalanced["fills"] if fill["date"] == "2020-03-02"][0], "sell")
        self.assertTrue(reconcile_daily_proxy(rebalanced, frames)["ok"])
        tampered = deepcopy(rebalanced)
        tampered["fills"][0]["normalized_units"] += 1
        self.assertFalse(reconcile_daily_proxy(tampered, frames)["ok"])

    def test_future_perturbation_prefix_replay_and_scale_invariance(self):
        frames = fixture()
        config = {"kind": "sector_momentum"}
        complete = simulate_sector_daily(frames, config, "2020-01-30", "2020-03-03")
        prefix = simulate_sector_daily(frames, config, "2020-01-30", "2020-02-14")
        self.assertEqual(prefix["rows"], [row for row in complete["rows"] if row["date"] <= "2020-02-14"])
        self.assertEqual(prefix["decisions"], [row for row in complete["decisions"] if row["date"] <= "2020-02-14"])
        altered = deepcopy(frames)
        for symbol in SECTOR_UNIVERSE:
            future = altered[symbol].index >= pd.Timestamp("2020-02-18", tz="America/New_York")
            price(altered, symbol, future, 700)
        changed = simulate_sector_daily(altered, config, "2020-01-30", "2020-03-03")
        self.assertEqual(prefix["rows"], [row for row in changed["rows"] if row["date"] <= "2020-02-14"])
        self.assertEqual(prefix["decisions"], [row for row in changed["decisions"] if row["date"] <= "2020-02-14"])
        frames["XLB"]["Adj Close"] *= 0.5
        scaled = simulate_sector_daily(frames, config, "2020-01-30", "2020-03-03")
        self.assertEqual(complete["decisions"], scaled["decisions"])
        np.testing.assert_allclose([row["equity"] for row in complete["rows"]], [row["equity"] for row in scaled["rows"]])


if __name__ == "__main__":
    unittest.main()
