"""Monthly signals on daily total-return proxies; never raw-share order fills."""
import math
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import Field

from .calendar import MarketCalendar
from .config import Settings


class DailyPolicySpec(Settings):
    kind: Literal["sma_cash", "relative_momentum", "buy_hold", "equal_weight"]
    lookback: int = Field(default=126, ge=63, le=252)
    rebalance: Literal["month_end"] = "month_end"
    max_gross_weight: float = Field(default=1.0, ge=0, le=1)


SECTOR_SYMBOLS = ("XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY")
SECTOR_UNIVERSE = SECTOR_SYMBOLS + ("SPY",)


class SectorPolicySpec(Settings):
    kind: Literal["sector_momentum", "sector_equal_weight", "buy_hold"]
    lookback: Literal[126, 252] = 252
    holdings: Literal[1, 3] = 3
    skip_sessions: Literal[21] = 21
    rebalance: Literal["month_end"] = "month_end"
    max_gross_weight: float = Field(default=1.0, ge=0, le=1)


def _dates(frame):
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.hasnans:
        raise ValueError("Daily observations require a finite DatetimeIndex")
    index = frame.index.tz_convert("America/New_York") if frame.index.tz is not None else frame.index
    if any(stamp != stamp.normalize() for stamp in index):
        raise ValueError("Daily observations must be labelled by exchange-local midnight")
    return pd.Index([stamp.date().isoformat() for stamp in index])


def validate_daily_frames(frames, session_dates):
    """Report exact requested session coverage; never fill, trim or repair data."""
    expected = pd.Index(session_dates)
    errors, instruments = [], {}
    if not frames or not len(expected) or expected.has_duplicates or not expected.is_monotonic_increasing:
        errors.append("Require instruments and distinct chronological requested XNYS sessions")
    required = ["Open", "High", "Low", "Close", "Adj Close", "Volume"]
    for symbol, frame in frames.items():
        item = {"rows": len(frame), "missing_count": None, "duplicate_count": None}
        instruments[symbol] = item
        try:
            dates = _dates(frame)
            missing, extra = expected.difference(dates), dates.difference(expected)
            item.update(missing_count=len(missing), unexpected_count=len(extra), duplicate_count=int(dates.duplicated().sum()),
                        first_missing=missing[0] if len(missing) else None)
            if dates.has_duplicates or not dates.is_monotonic_increasing or len(missing) or len(extra):
                errors.append(f"{symbol}: missing, duplicate, unexpected or unordered daily observations")
            if not set(required).issubset(frame.columns):
                raise ValueError("missing OHLCV or Adj Close columns")
            values = frame[required].to_numpy(dtype=float)
            if not np.isfinite(values).all() or (values[:, :5] <= 0).any() or (values[:, 5] < 0).any():
                raise ValueError("nonfinite/nonpositive prices or invalid volume")
            if (frame.High < frame[["Open", "Close", "Low"]].max(axis=1)).any() or (frame.Low > frame[["Open", "Close", "High"]].min(axis=1)).any():
                raise ValueError("inconsistent daily OHLC range")
        except (ValueError, TypeError, AttributeError) as error:
            errors.append(f"{symbol}: {error}")
    return {"usable": not errors, "errors": errors, "instruments": instruments,
            "warnings": ["Aggregated daily bars do not establish opening-auction liquidity or executable prices",
                         "Adjusted series are provider total-return proxies, revised retrospectively; not point-in-time observations",
                         "Normalized fractional research units are not tradable raw shares; distributions are not credited again"]}


def simulate_daily(frames, config, start, end, *, cost_bps=5.0, initial_cash=100000.0):
    """Carry normalized units overnight; completed month-end signals trade next open."""
    policy = config if isinstance(config, DailyPolicySpec) else DailyPolicySpec.model_validate(config)
    if set(frames) != {"SPY", "IEF", "GLD"}:
        raise ValueError("The pilot uses exactly SPY, IEF and GLD; universe changes require a new protocol")
    return _simulate_daily(frames, policy, start, end, ["SPY", "IEF", "GLD"], _daily_target,
                           cost_bps=cost_bps, initial_cash=initial_cash)


def simulate_sector_daily(frames, config, start, end, *, cost_bps=5.0, initial_cash=100000.0):
    """Screen the frozen nine-sector universe; SPY is a separate passive benchmark."""
    policy = config if isinstance(config, SectorPolicySpec) else SectorPolicySpec.model_validate(config)
    if set(frames) != set(SECTOR_UNIVERSE):
        raise ValueError("The sector pilot requires exactly the nine original sector ETFs and SPY")
    return _simulate_daily(frames, policy, start, end, list(SECTOR_UNIVERSE), _sector_target,
                           cost_bps=cost_bps, initial_cash=initial_cash)


def _daily_target(policy, history, symbols):
    target = {symbol: 0.0 for symbol in symbols}
    reason = "Insufficient completed observations; cash target"
    if policy.kind == "buy_hold":
        target["SPY"] = policy.max_gross_weight
        reason = "SPY passive reference, held through evaluation end"
    elif policy.kind == "equal_weight":
        target = {symbol: policy.max_gross_weight / len(symbols) for symbol in symbols}
        reason = "Monthly equal-weight passive reference"
    elif policy.kind == "sma_cash" and len(history) >= policy.lookback:
        target["SPY"] = policy.max_gross_weight if history.SPY.iloc[-1] > history.SPY.iloc[-policy.lookback:].mean() else 0.0
        reason = "SPY above trailing completed-close SMA" if target["SPY"] else "SPY at/below SMA; cash"
    elif policy.kind == "relative_momentum" and len(history) > policy.lookback:
        momentum = history.iloc[-1] / history.iloc[-policy.lookback - 1] - 1
        winner = max(symbols, key=lambda symbol: momentum[symbol])
        if momentum[winner] > 0:
            target[winner] = policy.max_gross_weight
        reason = f"Highest {policy.lookback}-session return: {winner}; positive-only allocation"
    return target, reason


def _sector_target(policy, history, symbols):
    target = {symbol: 0.0 for symbol in symbols}
    reason = "Insufficient completed observations; cash target"
    if policy.kind == "buy_hold":
        target["SPY"] = policy.max_gross_weight
        reason = "SPY passive reference, held through evaluation end"
    elif policy.kind == "sector_equal_weight":
        target.update({symbol: policy.max_gross_weight / len(SECTOR_SYMBOLS) for symbol in SECTOR_SYMBOLS})
        reason = "Monthly equal-weight nine-sector passive reference"
    elif len(history) > policy.lookback:
        momentum = history.iloc[-policy.skip_sessions - 1] / history.iloc[-policy.lookback - 1] - 1
        ranked = sorted(SECTOR_SYMBOLS, key=lambda symbol: -momentum[symbol])
        for symbol in ranked[:policy.holdings]:
            target[symbol] = policy.max_gross_weight / policy.holdings
        reason = (f"Top {policy.holdings} sectors by return from t-{policy.lookback} to t-{policy.skip_sessions}: "
                  + ", ".join(ranked[:policy.holdings]) + "; no positive-return filter")
    return target, reason


def _validated_proxy_target(target, reason, symbols, position_cap):
    """Validate a new protocol's proposal before it reaches execution."""
    from .strategies import Decision
    decision = Decision.model_validate({"weights": target, "reason": reason})
    if set(decision.weights) != set(symbols):
        raise ValueError("Proxy target must contain exactly the declared instruments")
    if sum(decision.weights.values()) > 1 + 1e-9:
        raise ValueError("Proxy target exceeds the long-only gross limit of one")
    if any(weight > position_cap + 1e-9 for weight in decision.weights.values()):
        raise ValueError("Proxy target exceeds the declared per-position cap")
    return decision.weights, decision.reason


def _simulate_daily(frames, policy, start, end, symbols, target_at_close, *, cost_bps, initial_cash,
                    signal_schedule="month_end", position_cap=1.0):
    """Shared next-open execution and accounting for daily proxy research protocols."""
    if isinstance(cost_bps, bool) or not math.isfinite(cost_bps) or not 0 <= cost_bps <= 1000:
        raise ValueError("cost_bps must be a finite one-way rate between 0 and 1000")
    if isinstance(initial_cash, bool) or not math.isfinite(initial_cash) or initial_cash <= 0:
        raise ValueError("initial_cash must be positive and finite")
    if signal_schedule not in {"month_end", "week_end"}:
        raise ValueError("Unknown daily proxy signal schedule")
    if any(frame.empty for frame in frames.values()):
        raise ValueError("Daily observations are unavailable for at least one requested instrument")
    calendar = MarketCalendar()
    dated = {symbol: frame.set_axis(_dates(frame)) for symbol, frame in frames.items()}
    first = min(frame.index.min() for frame in dated.values())
    last = max(frame.index.max() for frame in dated.values())
    full_dates = [session.date for session in calendar.sessions(first, last)]
    quality = validate_daily_frames(frames, full_dates)
    if not quality["usable"]:
        raise ValueError("Daily dataset quality failed: " + "; ".join(quality["errors"]))
    sessions = calendar.sessions(start, end)
    if not sessions or any(session.date not in full_dates for session in sessions):
        raise ValueError("Evaluation requires every requested XNYS session in the supplied dataset")
    # The following official session is calendar information, not a future price.
    schedule = calendar.sessions(sessions[0].date, (pd.Timestamp(end) + pd.Timedelta(days=10)).date().isoformat())
    following = {left.date: right.date for left, right in zip(schedule, schedule[1:])}
    closes = pd.DataFrame({symbol: frame["Adj Close"].astype(float) for symbol, frame in dated.items()})
    opens = pd.DataFrame({symbol: frame.Open.astype(float) * frame["Adj Close"].astype(float) / frame.Close.astype(float)
                          for symbol, frame in dated.items()})
    cash, units, rate = float(initial_cash), {symbol: 0.0 for symbol in symbols}, cost_bps / 10000
    rows, decisions, fills, pending = [], [], [], None
    total_cost, peak, worst = 0.0, initial_cash, 0.0
    for session in sessions:
        day = session.date
        prices = opens.loc[day].to_dict()
        opening_equity = cash + sum(units[symbol] * prices[symbol] for symbol in symbols)
        day_cost, traded = 0.0, 0.0
        if pending is not None:
            target, signal_date = pending
            quantities = {symbol: opening_equity * target[symbol] / prices[symbol] for symbol in symbols}

            def trade(symbol, side, quantity):
                nonlocal cash, total_cost, day_cost, traded
                if quantity <= 1e-10:
                    return
                notional = quantity * prices[symbol]
                cost = notional * rate
                cash += notional - cost if side == "sell" else -notional - cost
                units[symbol] += -quantity if side == "sell" else quantity
                total_cost += cost
                day_cost += cost
                traded += notional
                fills.append({"timestamp": session.open.isoformat(), "date": day, "signal_date": signal_date, "symbol": symbol,
                              "side": side, "normalized_units": quantity, "proxy_price": prices[symbol], "notional": notional,
                              "cost": cost, "cash_after": cash, "execution_model": "fractional total-return proxy; not a raw-share fill"})

            for symbol in symbols:
                trade(symbol, "sell", max(0.0, units[symbol] - quantities[symbol]))
            demand = {symbol: max(0.0, quantities[symbol] - units[symbol]) for symbol in symbols}
            needed = sum(demand[symbol] * prices[symbol] * (1 + rate) for symbol in symbols)
            scale = min(1.0, max(0.0, cash) / needed) if needed else 0.0
            for symbol in symbols:
                trade(symbol, "buy", demand[symbol] * scale)
            if cash < -1e-7 or min(units.values()) < -1e-10:
                raise AssertionError("Proxy execution created borrowing or short positions")
            cash = max(0.0, cash)
            pending = None
        closing = closes.loc[day].to_dict()
        equity = cash + sum(units[symbol] * closing[symbol] for symbol in symbols)
        peak = max(peak, equity)
        worst = max(worst, 1 - equity / peak)
        weights = {symbol: units[symbol] * closing[symbol] / equity for symbol in symbols}
        rows.append({"date": day, "timestamp": session.close.isoformat(), "equity": equity, "cash": cash,
                     "weights": weights, "normalized_units": units.copy(), "valuation_prices": closing,
                     "turnover": traded / opening_equity, "cost": day_cost, "cumulative_cost": total_cost,
                     "drawdown_pct": (1 - equity / peak) * 100, "fill_count": len(fills)})
        signal_day = (day[:7] != following[day][:7] if signal_schedule == "month_end" else
                      pd.Timestamp(day).isocalendar()[:2] != pd.Timestamp(following[day]).isocalendar()[:2])
        if signal_day and (policy.kind != "buy_hold" or not decisions):
            history = closes.loc[:day]
            target, reason = target_at_close(policy, history, symbols)
            if signal_schedule == "week_end":
                target, reason = _validated_proxy_target(target, reason, symbols, position_cap)
            decisions.append({"date": day, "timestamp": session.close.isoformat(), "execute_date": following[day],
                              "weights": target, "reason": reason, "completed_observations": len(history)})
            pending = target, day
    returns = pd.Series([initial_cash] + [row["equity"] for row in rows]).pct_change().dropna()
    volatility = float(returns.std(ddof=1)) if len(returns) > 1 else 0.0
    years = (sessions[-1].close - sessions[0].open).total_seconds() / (365.25 * 86400)
    metrics = {"initial_equity": initial_cash, "final_equity": rows[-1]["equity"],
               "return_pct": (rows[-1]["equity"] / initial_cash - 1) * 100, "max_drawdown_pct": worst * 100,
               "cagr_pct": math.expm1(math.log(rows[-1]["equity"] / initial_cash) / years) * 100,
               "avg_exposure_pct": sum(sum(row["weights"].values()) for row in rows) / len(rows) * 100,
               "annualized_volatility_pct": volatility * math.sqrt(252) * 100 if len(returns) >= 30 else None,
               "total_cost": total_cost, "gross_turnover": sum(row["turnover"] for row in rows), "fills": len(fills),
               "sessions": len(rows), "daily_sharpe_zero_risk_free": float(returns.mean() / volatility * math.sqrt(252)) if len(returns) >= 30 and volatility > 0 else None}
    result = {"schema_version": "1.0.0", "policy": policy.model_dump(), "start": start, "end": end, "cost_bps": cost_bps,
            "execution_model": "normalized fractional total-return proxy; no real orders", "rows": rows,
            "decisions": decisions, "fills": fills, "metrics": metrics, "pending_target": pending[0] if pending else None,
            "quality": quality, "assessment": "inconclusive", "limitations": quality["warnings"] + [
                "Cash earns zero; fractional adjusted units embed provider distribution-reinvestment assumptions",
                "Opening execution uses adjusted daily open plus fixed one-way bps; no spread, auction, taxes or market-impact model",
                ("All policies start in cash and first target an in-period month-end; final holdings remain marked, without invented liquidation" if signal_schedule == "month_end" else
                 "All policies start in cash and first target an in-period final weekly session; final holdings remain marked, without invented liquidation"),
                "Historical proxy results alone cannot establish a deployable edge; raw-share accounting and forward paper evidence remain required"]}
    if signal_schedule == "week_end":
        result["signal_schedule"] = signal_schedule
    return result


def reconcile_daily_proxy(result, frames):
    """Rebuild every mark from source prices and normalized-unit trades independently."""
    errors, checked = [], 0

    def same(actual, expected, label):
        if isinstance(actual, bool) or not isinstance(actual, (int, float)) or not math.isfinite(actual) or not math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-7):
            errors.append(f"{label}: recorded {actual!r}, reconstructed {expected!r}")

    try:
        source = {}
        for symbol, frame in frames.items():
            index = frame.index.tz_convert("America/New_York") if frame.index.tz is not None else frame.index
            if index.normalize().has_duplicates:
                raise ValueError(f"{symbol}: duplicate source session")
            source[symbol] = {stamp.date().isoformat(): bar for stamp, (_, bar) in zip(index, frame.iterrows())}
        schedule = MarketCalendar().sessions(result["start"], result["end"])
        if [row["date"] for row in result["rows"]] != [session.date for session in schedule]:
            raise ValueError("Reported marks differ from requested XNYS sessions")
        preceding = {right.date: left.date for left, right in zip(schedule, schedule[1:])}
        signal_schedule = result.get("signal_schedule", "month_end")
        if signal_schedule not in {"month_end", "week_end"} or result["policy"]["rebalance"] != signal_schedule:
            raise ValueError("Unknown or inconsistent proxy signal schedule")
        weekly_decisions = {}
        if signal_schedule == "week_end":
            extended = MarketCalendar().sessions(schedule[0].date, (pd.Timestamp(result["end"]) + pd.Timedelta(days=10)).date().isoformat())
            following = {left.date: right.date for left, right in zip(extended, extended[1:])}
            # Compare ISO year/week independently of prices and the policy's signal code.
            week = lambda day: pd.Timestamp(day).date().isocalendar()[:2]
            expected = [session.date for session in schedule if week(session.date) != week(following[session.date])]
            if result["policy"]["kind"] == "buy_hold":
                expected = expected[:1]
            if [decision["date"] for decision in result["decisions"]] != expected:
                raise ValueError("Weekly decisions differ from the official final-session schedule")
            cap = 1 / result["policy"]["holdings"] if result["policy"]["kind"] == "weekly_reversal" else 1.0
            by_date = {session.date: session for session in schedule}
            for decision in result["decisions"]:
                day, weights = decision["date"], decision["weights"]
                if decision["timestamp"] != by_date[day].close.isoformat() or decision["execute_date"] != following[day]:
                    raise ValueError("Weekly decision has an invalid close or next-session execution timestamp")
                if set(weights) != set(source) or any(isinstance(weight, bool) or not isinstance(weight, (int, float)) or not math.isfinite(weight) or not 0 <= weight <= cap + 1e-9 for weight in weights.values()) or sum(weights.values()) > 1 + 1e-9:
                    raise ValueError("Weekly decision violates the declared long-only target limits")
                weekly_decisions[day] = decision
        cash = float(result["metrics"]["initial_equity"])
        units, applied, total_cost = {symbol: 0.0 for symbol in source}, 0, 0.0
        fills, rate = result["fills"], result["cost_bps"] / 10000
        for row, session in zip(result["rows"], schedule):
            day = row["date"]
            opening = {symbol: float(bars[day]["Open"] * bars[day]["Adj Close"] / bars[day]["Close"]) for symbol, bars in source.items()}
            opening_equity = cash + sum(units[symbol] * opening[symbol] for symbol in units)
            count, day_cost, traded = row["fill_count"], 0.0, 0.0
            if type(count) is not int or not applied <= count <= len(fills):
                raise ValueError(f"{day}: invalid applied fill count")
            for number in range(applied, count):
                fill = fills[number]
                symbol, quantity, side = fill["symbol"], fill["normalized_units"], fill["side"]
                if symbol not in units or side not in {"buy", "sell"} or isinstance(quantity, bool) or not math.isfinite(quantity) or quantity <= 0:
                    raise ValueError(f"Fill {number}: invalid symbol, side or normalized units")
                invalid_schedule = (fill["signal_date"][:7] == day[:7] if signal_schedule == "month_end" else
                                    fill["signal_date"] not in weekly_decisions or weekly_decisions[fill["signal_date"]]["execute_date"] != day)
                if fill["date"] != day or fill["timestamp"] != session.open.isoformat() or fill["signal_date"] != preceding.get(day) or invalid_schedule:
                    errors.append(f"Fill {number}: invalid execution/signal timestamp")
                notional, sign = quantity * opening[symbol], 1 if side == "buy" else -1
                fee = notional * rate
                cash -= sign * notional + fee
                units[symbol] += sign * quantity
                same(fill["proxy_price"], opening[symbol], f"fill {number} source open")
                same(fill["notional"], notional, f"fill {number} notional")
                same(fill["cost"], fee, f"fill {number} fee")
                same(fill["cash_after"], cash, f"fill {number} cash")
                if cash < -1e-7 or units[symbol] < -1e-9:
                    errors.append(f"Fill {number}: borrowing or short position")
                day_cost, traded = day_cost + fee, traded + notional
            applied, total_cost = count, total_cost + day_cost
            closing = {symbol: float(bars[day]["Adj Close"]) for symbol, bars in source.items()}
            equity = cash + sum(units[symbol] * closing[symbol] for symbol in units)
            for key, expected in [("cash", cash), ("equity", equity), ("cost", day_cost), ("cumulative_cost", total_cost), ("turnover", traded / opening_equity)]:
                same(row[key], expected, f"{day} {key}")
            if row["timestamp"] != session.close.isoformat():
                errors.append(f"{day}: incorrect valuation timestamp")
            for symbol in units:
                same(row["normalized_units"][symbol], units[symbol], f"{day} {symbol} units")
                same(row["valuation_prices"][symbol], closing[symbol], f"{day} {symbol} source close")
                same(row["weights"][symbol], units[symbol] * closing[symbol] / equity, f"{day} {symbol} weight")
            checked += 1
        if applied != len(fills):
            errors.append("Final mark excludes recorded fills")
        same(result["metrics"]["final_equity"], equity, "final equity")
        same(result["metrics"]["total_cost"], total_cost, "total cost")
    except (KeyError, TypeError, ValueError, IndexError, AttributeError, ZeroDivisionError) as error:
        errors.append(str(error))
    return {"ok": not errors, "errors": errors, "rows_checked": checked, "fills_checked": applied if "applied" in locals() else 0}
