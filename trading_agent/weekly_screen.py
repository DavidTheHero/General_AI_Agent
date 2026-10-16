"""Frozen weekly reversal proposals using only completed adjusted-close observations."""
from datetime import date
import math
from typing import Literal

import numpy as np
import pandas as pd
from .calendar import MarketCalendar
from .config import Settings
from .daily_screen import _simulate_daily, _validated_proxy_target


WEEKLY_UNIVERSE = ("SPY", "IWM", "QQQ", "EFA", "EEM", "IEF", "TLT", "GLD", "DBC")


class WeeklyReversalPolicySpec(Settings):
    kind: Literal["weekly_reversal", "equal_weight", "buy_hold", "training_allocation"] = "weekly_reversal"
    lookback: Literal[1, 5] = 5
    holdings: Literal[1, 3] = 3
    volatility_sessions: Literal[63] = 63
    rebalance: Literal["week_end"] = "week_end"
    max_gross_weight: Literal[1.0] = 1.0


def _weekly_target(policy, history, symbols, allocations):
    target = {symbol: 0.0 for symbol in symbols}
    if policy.kind == "buy_hold":
        target["SPY"] = 1.0
        return target, "SPY passive context reference; first weekly opportunity only"
    if policy.kind == "equal_weight":
        return {symbol: 1 / len(symbols) for symbol in symbols}, "Weekly equal-weight declared ETF basket"
    if policy.kind == "training_allocation":
        day = pd.Timestamp(history.index[-1])
        sessions = MarketCalendar().sessions(day.date().isoformat(), (day + pd.Timedelta(days=10)).date().isoformat())
        execute_date = sessions[1].date
        eligible = [start for start in allocations if start <= execute_date]
        if not eligible:
            return target, "No frozen training allocation is available for the next session; cash target"
        start = max(eligible)
        return allocations[start].copy(), f"Prior-observations allocation frozen for fold beginning {start}; next-session activation"
    length = policy.lookback
    if len(history) < length + 64:
        return target, f"Need {length + 64} completed closes; cash before volatility warm-up"
    # This 64-close window yields exactly 63 returns, ending at t-L.
    window = history.iloc[-length - 64:-length]
    sigma = np.log(window / window.shift(1)).iloc[1:].std(ddof=1)
    if any(not math.isfinite(float(value)) or value <= 0 for value in sigma):
        raise ValueError("Weekly reversal requires finite, strictly positive lagged 63-return volatility for every ETF")
    score = np.log(history.iloc[-1] / history.iloc[-length - 1]) / (math.sqrt(length) * sigma)
    if not np.isfinite(score.to_numpy()).all():
        raise ValueError("Weekly reversal produced a nonfinite score")
    ranked = sorted(symbols, key=lambda symbol: float(score[symbol]))
    for symbol in ranked[:policy.holdings]:
        target[symbol] = 1 / policy.holdings
    return target, (f"Lowest {policy.holdings} lagged-volatility-normalized {length}-session log returns: "
                    + ", ".join(ranked[:policy.holdings]))


def simulate_weekly_reversal(frames, config, start, end, *, cost_bps=5.0, initial_cash=100000.0,
                             allocation_by_fold=None):
    """Propose weekly long-only targets; the shared host validates and executes them."""
    policy = config if isinstance(config, WeeklyReversalPolicySpec) else WeeklyReversalPolicySpec.model_validate(config)
    if set(frames) != set(WEEKLY_UNIVERSE):
        raise ValueError("Weekly reversal requires exactly the frozen nine-ETF universe")
    allocations = {}
    if policy.kind == "training_allocation":
        if not isinstance(allocation_by_fold, dict) or not allocation_by_fold:
            raise ValueError("The training-allocation reference requires explicit frozen fold weights")
        for fold_start, weights in allocation_by_fold.items():
            if not isinstance(fold_start, str) or date.fromisoformat(fold_start).isoformat() != fold_start:
                raise ValueError("Training-allocation fold dates must be exact ISO dates")
            allocations[fold_start] = _validated_proxy_target(weights, "Frozen training allocation", WEEKLY_UNIVERSE, 1.0)[0]
        allocations = dict(sorted(allocations.items()))
    elif allocation_by_fold is not None:
        raise ValueError("Frozen fold weights apply only to the training-allocation reference")
    result = _simulate_daily(frames, policy, start, end, list(WEEKLY_UNIVERSE),
        lambda policy, history, symbols: _weekly_target(policy, history, symbols, allocations),
        cost_bps=cost_bps, initial_cash=initial_cash, signal_schedule="week_end",
        position_cap=1 / policy.holdings if policy.kind == "weekly_reversal" else 1.0)
    if policy.kind == "training_allocation":
        result["allocation_by_fold"] = allocations
        result["allocation_activation"] = "next_session_open"
    return result
