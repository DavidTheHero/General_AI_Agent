"""Metrics from actual simulated fills and observed equity, with explicit units."""
import math

import numpy as np


def equity_curve(sessions):
    rows = []
    benchmark_capital = sessions[0]["initial_equity"] if sessions else 0
    for session in sessions:
        initial = session["initial_equity"]
        for item in session["equity"]:
            rows.append({**item, "session": session["session"], "benchmark_equity":
                         item["benchmark_equity"] / initial * benchmark_capital if initial > 0 else benchmark_capital})
        if session["equity"] and initial > 0:
            benchmark_capital *= session["equity"][-1]["benchmark_equity"] / initial
    peak = None
    for row in rows:
        peak = row["equity"] if peak is None else max(peak, row["equity"])
        row["drawdown"] = row["equity"] / peak - 1 if peak else 0
    return rows


def performance_metrics(sessions, initial_cash):
    curve = equity_curve(sessions)
    fills = [fill for session in sessions for fill in session["fills"]]
    closes = [fill for fill in fills if fill["side"] == "sell"]
    gains = sum(max(fill["realized_pnl"], 0) for fill in closes)
    losses = abs(sum(min(fill["realized_pnl"], 0) for fill in closes))
    daily_returns = [session["final_equity"] / session["initial_equity"] - 1 for session in sessions if session["finished"] and session["initial_equity"] > 0]
    standard_deviation = float(np.std(daily_returns, ddof=1)) if len(daily_returns) >= 2 else None
    sharpe = float(np.mean(daily_returns) / standard_deviation * math.sqrt(252)) if standard_deviation and standard_deviation > 1e-12 else None
    final = curve[-1]["equity"] if curve else None
    commissions = sum(fill["commission"] for fill in fills)
    slippage = sum(fill["slippage_cost"] for fill in fills)
    minutes = sum(row.get("duration_minutes", 0) for row in curve)
    return {
        "initial_equity": initial_cash, "final_equity": final,
        "net_pnl": final - initial_cash if final is not None else None,
        "return_pct": (final / initial_cash - 1) * 100 if final is not None else None,
        "benchmark_return_pct": (curve[-1]["benchmark_equity"] / initial_cash - 1) * 100 if curve else None,
        "max_drawdown_pct": max(0, -min(row["drawdown"] for row in curve) * 100) if curve else None,
        "realized_pnl": sum(fill["realized_pnl"] for fill in closes),
        "unrealized_pnl": final - initial_cash - sum(fill["realized_pnl"] for fill in closes) if final is not None else None,
        "commission_cost": commissions, "slippage_cost": slippage,
        "pnl_before_direct_costs": final - initial_cash + commissions + slippage if final is not None else None,
        "fills": len(fills), "closed_fills": len(closes),
        "closed_fill_win_rate_pct": sum(fill["realized_pnl"] > 0 for fill in closes) / len(closes) * 100 if closes else None,
        "profit_factor": gains / losses if losses else None,
        "gross_turnover": sum(fill["quantity"] * fill["fill_price"] for fill in fills) / initial_cash,
        "average_exposure_pct": sum(row.get("bar_exposure", 0) * row.get("duration_minutes", 0) for row in curve) / minutes * 100 if minutes else None,
        "completed_sessions": sum(session["finished"] for session in sessions), "reported_sessions": len(sessions),
        "daily_sharpe_zero_risk_free": sharpe,
        "annualized_daily_volatility_pct": standard_deviation * math.sqrt(252) * 100 if standard_deviation is not None else None,
        "decision_errors": sum(bool(decision["error"]) for session in sessions for decision in session["decisions"]),
    }
