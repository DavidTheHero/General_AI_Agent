"""Independent fill-ledger reconstruction; never calls Portfolio or its helpers."""
import math

import pandas as pd

from .config import AgentConfig


def reconcile_session(result, config):
    config = config if isinstance(config, AgentConfig) else AgentConfig.model_validate(config)
    errors = []

    def same(actual, expected, label):
        if isinstance(actual, bool) or not isinstance(actual, (int, float)) or not math.isfinite(actual) or not math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-7):
            errors.append(f"{label}: recorded {actual!r}, reconstructed {expected!r}")

    cash = float(result["initial_equity"])
    quantity = {symbol: 0 for symbol in config.symbols}
    basis = {symbol: 0.0 for symbol in config.symbols}
    states = [(cash, quantity.copy(), basis.copy())]
    bars = {symbol: {pd.Timestamp(row["timestamp"]): row for row in result.get("prices", {}).get(symbol, [])} for symbol in config.symbols}
    session_close = pd.Timestamp(result["session_close"])
    opening_errors = {pd.Timestamp(event["timestamp"]): event["observed_open_prices"] for event in result.get("events", []) if event.get("observed_open_prices")}
    fills = result.get("fills", [])
    timestamps = []
    realized_total, commissions, slippage = 0.0, 0.0, 0.0
    for number, fill in enumerate(fills):
        label = f"fill {number}"
        try:
            timestamp = pd.Timestamp(fill["timestamp"])
            if pd.isna(timestamp) or timestamp.tzinfo is None or (timestamps and timestamp < timestamps[-1]):
                raise ValueError("nonchronological or timezone-naive timestamp")
            timestamps.append(timestamp)
            symbol, side, count = fill["symbol"], fill["side"], fill["quantity"]
            if symbol not in quantity or side not in {"buy", "sell"} or type(count) is not int or count <= 0:
                raise ValueError("invalid symbol, side or whole-share quantity")
            reference = fill["reference_price"]
            if isinstance(reference, bool) or not isinstance(reference, (float, int)) or not math.isfinite(reference) or reference <= 0:
                raise ValueError("invalid reference price")
            observed = bars[symbol].get(timestamp)
            known_price = observed["Open"] if observed else opening_errors.get(timestamp, {}).get(symbol)
            if timestamp == session_close and bars[symbol]:
                known_price = bars[symbol][max(bars[symbol])]["Close"]
            if known_price is None:
                errors.append(f"{label}: no observed market price at fill timestamp")
            else:
                same(reference, known_price, f"{label} reference price")
            price = reference * (1 + (1 if side == "buy" else -1) * config.costs.slippage_bps / 10000)
            fee = count * price * config.costs.commission_bps / 10000 + config.costs.fixed_fee
            slip = count * abs(price - reference)
            same(fill.get("fill_price"), price, f"{label} fill price")
            same(fill.get("commission"), fee, f"{label} commission")
            same(fill.get("slippage_cost"), slip, f"{label} slippage")
            pnl = 0.0
            if side == "buy":
                cash -= count * price + fee
                basis[symbol] += count * price + fee
                quantity[symbol] += count
            elif count > quantity[symbol]:
                raise ValueError("sell exceeds independently reconstructed holdings")
            else:
                sold_basis = basis[symbol] * count / quantity[symbol]
                pnl = count * price - fee - sold_basis
                cash += count * price - fee
                basis[symbol] -= sold_basis
                quantity[symbol] -= count
                if not quantity[symbol]:
                    basis[symbol] = 0.0
            same(fill.get("realized_pnl"), pnl, f"{label} realized P&L")
            if cash < -1e-7:
                errors.append(f"{label}: negative reconstructed cash")
            realized_total += pnl
            commissions += fee
            slippage += slip
        except (KeyError, TypeError, ValueError, OverflowError) as error:
            errors.append(f"{label}: {error}")
        states.append((cash, quantity.copy(), basis.copy()))

    final_prices = {}
    previous_count = 0
    previous_mark = None
    for number, row in enumerate(result.get("equity", [])):
        label = f"mark {number}"
        timestamp = pd.Timestamp(row["timestamp"])
        if timestamp.tzinfo is None or pd.isna(timestamp) or (previous_mark is not None and timestamp < previous_mark):
            errors.append(f"{label}: nonchronological or timezone-naive timestamp")
            continue
        previous_mark = timestamp
        count = row.get("fill_count", sum(stamp < timestamp or timestamp == session_close for stamp in timestamps))
        if type(count) is not int or count < previous_count or not 0 <= count < len(states):
            errors.append(f"{label}: invalid applied fill count")
            continue
        previous_count = count
        if any(stamp > timestamp for stamp in timestamps[:count]) or any(stamp < timestamp for stamp in timestamps[count:]):
            errors.append(f"{label}: applied fills conflict with mark timestamp")
        mark_cash, mark_quantity, _ = states[count]
        prices = row.get("valuation_prices", {})
        expected_prices = {}
        for symbol, history in bars.items():
            if timestamp in opening_errors and row.get("duration_minutes", 0) == 0:
                expected = opening_errors[timestamp].get(symbol)
            elif number == 0 and history:
                expected = history[min(history)]["Open"]
            else:
                completed = [bar for start, bar in history.items() if min(start + pd.Timedelta(minutes=config.minutes), session_close) == timestamp]
                expected = completed[-1]["Close"] if completed else None
            if expected is None:
                errors.append(f"{label}: no observed valuation price for {symbol}")
                continue
            expected_prices[symbol] = expected
            if prices:
                same(prices.get(symbol), expected, f"{label} {symbol} valuation price")
        if set(expected_prices) != set(config.symbols):
            continue
        exposure = sum(mark_quantity[symbol] * expected_prices[symbol] for symbol in config.symbols)
        same(row.get("cash"), mark_cash, f"{label} cash")
        same(row.get("equity"), mark_cash + exposure, f"{label} equity")
        same(row.get("gross_exposure"), exposure, f"{label} exposure")
        final_prices = expected_prices

    final_equity = cash + sum(quantity[symbol] * final_prices.get(symbol, 0) for symbol in config.symbols)
    if any(quantity.values()) and set(final_prices) != set(config.symbols):
        errors.append("Open holdings have no independently observed final valuation")
    same(result.get("final_equity"), final_equity, "final equity")
    if result.get("equity"):
        if previous_count != len(fills):
            errors.append("Final mark does not include every recorded fill")
        if result.get("valuation_timestamp") != result["equity"][-1]["timestamp"]:
            errors.append("Final valuation timestamp differs from final equity mark")
        same(result["equity"][-1].get("equity"), final_equity, "final equity mark")
    if result.get("equity") and set(result.get("holdings", {})) != set(config.symbols):
        errors.append("Final holdings must report every configured symbol")
    for symbol, holding in result.get("holdings", {}).items():
        if symbol not in quantity:
            errors.append(f"Unknown final holding {symbol}")
            continue
        same(holding.get("quantity"), quantity[symbol], f"{symbol} final quantity")
        average = basis[symbol] / quantity[symbol] if quantity[symbol] else 0
        same(holding.get("average_cost"), average, f"{symbol} average cost")
        same(holding.get("market_value"), quantity[symbol] * final_prices.get(symbol, 0), f"{symbol} market value")
    if result.get("finished") and any(quantity.values()):
        errors.append("Finished intraday session has open holdings")
    return {"ok": not errors, "errors": errors, "cash": cash, "final_equity": final_equity,
            "quantities": quantity, "realized_pnl": realized_total, "commission_cost": commissions, "slippage_cost": slippage}
