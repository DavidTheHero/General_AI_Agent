"""Observe -> execute queued targets -> decide -> validate -> queue, one bar at a time."""
from dataclasses import asdict
from copy import deepcopy
import math
import logging
from numbers import Real

import pandas as pd

from .calendar import Session
from .config import AgentConfig
from .portfolio import Portfolio
from .strategies import Decision, Observation, Policy, make_policy


logger = logging.getLogger(__name__)


class IntradayAgent:
    def __init__(self, config: AgentConfig, session: Session, cash=None, policy: Policy | None = None):
        self.config, self.session = config, session
        self.policy = policy or make_policy(config.strategy)
        self.portfolio = Portfolio(config.initial_cash if cash is None else cash, config.symbols, config.costs)
        self.history = {symbol: pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"]) for symbol in config.symbols}
        self.pending = None
        self.equity_rows, self.decisions, self.events = [], [], []
        self.last_timestamp = None
        self.halt_reason = None
        self.consecutive_errors = 0
        self.initial_equity = self.portfolio.cash
        self.last_prices = None
        self.finished = False
        self.failed = False

    def _weights(self, decision):
        if set(decision.weights) != set(self.config.symbols):
            raise ValueError("Decision must specify every configured symbol and no others")
        if any(not math.isfinite(weight) or weight < 0 or weight > 1 for weight in decision.weights.values()) or sum(decision.weights.values()) > 1 + 1e-9:
            raise ValueError("Only finite, long-only weights with a total at most 1 are allowed")
        weights = {symbol: min(weight, self.config.risk.max_position_weight) for symbol, weight in decision.weights.items()}
        gross = sum(weights.values())
        if gross > self.config.strategy.target_gross_weight:
            weights = {symbol: weight * self.config.strategy.target_gross_weight / gross for symbol, weight in weights.items()}
        return weights

    def _mark(self, timestamp, prices, bar_exposure=0, duration_minutes=0):
        snapshot = self.portfolio.snapshot(prices)
        self.equity_rows.append({"timestamp": timestamp.isoformat(), "equity": snapshot["equity"], "cash": snapshot["cash"],
            "gross_exposure": sum(item["market_value"] for item in snapshot["positions"].values()),
            "bar_exposure": bar_exposure, "duration_minutes": duration_minutes,
            "valuation_prices": prices.copy(), "fill_count": len(self.portfolio.fills),
            "benchmark_equity": self.initial_equity * sum(prices[symbol] / self.benchmark_open[symbol] for symbol in self.config.symbols) / len(self.config.symbols)})
        self.last_prices = prices.copy()
        return snapshot

    def observe(self, timestamp, bars):
        timestamp = pd.Timestamp(timestamp)
        if pd.isna(timestamp) or timestamp.tzinfo is None:
            raise ValueError("Bar timestamp must be timezone-aware")
        timestamp = timestamp.tz_convert("UTC")
        if set(bars) != set(self.config.symbols):
            raise ValueError("Bars must specify every configured symbol and no others")
        validated = {}
        for symbol, bar in bars.items():
            values = {}
            for field in self.history[symbol].columns:
                value = bar.get(field)
                if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
                    raise ValueError(f"{symbol}: {field} must be finite numeric OHLCV")
                values[field] = float(value)
            if any(values[field] <= 0 for field in ["Open", "High", "Low", "Close"]) or values["Volume"] < 0:
                raise ValueError(f"{symbol}: prices must be positive and volume nonnegative")
            if values["High"] < max(values["Open"], values["Low"], values["Close"]) or values["Low"] > min(values["Open"], values["High"], values["Close"]):
                raise ValueError(f"{symbol}: inconsistent OHLCV range")
            validated[symbol] = values
        bars = validated
        if self.last_timestamp is not None and timestamp <= self.last_timestamp:
            if all(timestamp in self.history[symbol].index and self.history[symbol].loc[timestamp].to_dict() == bar for symbol, bar in bars.items()):
                return False
            raise ValueError("Conflicting duplicate or revised previously processed bar")
        if self.finished or self.failed:
            raise ValueError("Session already finished or failed")
        grid = self.session.grid(self.config.minutes)
        expected = grid[0] if self.last_timestamp is None else grid[grid.get_loc(self.last_timestamp) + 1]
        if timestamp != expected:
            raise ValueError("Bars must arrive in complete chronological session order")
        opening = {symbol: float(bar["Open"]) for symbol, bar in bars.items()}
        closing = {symbol: float(bar["Close"]) for symbol, bar in bars.items()}
        if self.last_timestamp is None:
            self.equity_rows.append({"timestamp": self.session.open.isoformat(), "equity": self.initial_equity,
                                     "cash": self.initial_equity, "gross_exposure": 0, "benchmark_equity": self.initial_equity, "bar_exposure": 0, "duration_minutes": 0,
                                     "valuation_prices": opening.copy(), "fill_count": 0})
            self.benchmark_open = opening.copy()
        if self.pending is not None:
            weights, reason = self.pending
            try:
                self.portfolio.rebalance(timestamp, weights, opening, reason)
            except (Exception, KeyboardInterrupt) as failure:
                self._mark(timestamp, opening)
                self.failed = True
                self.events.append({"timestamp": timestamp.isoformat(), "type": "execution_error", "message": str(failure), "observed_open_prices": opening})
                raise
            self.pending = None
        for symbol, bar in bars.items():
            self.history[symbol].loc[timestamp] = {key: float(bar[key]) for key in self.history[symbol].columns}
        end = self.session.bar_end(timestamp, self.config.minutes)
        equity = self.portfolio.equity(closing)
        if equity <= self.initial_equity * (1 - self.config.risk.daily_loss_limit) and not self.halt_reason:
            self.halt_reason = "daily_loss_limit"
            self.events.append({"timestamp": end.isoformat(), "type": self.halt_reason})
        bar_exposure = sum(self.portfolio.positions[symbol].quantity * closing[symbol] for symbol in self.config.symbols) / equity if equity > 0 else 0
        self.last_prices = closing.copy()
        self.last_timestamp = timestamp
        if end == self.session.close:
            try:
                self.portfolio.liquidate(end, closing, "Scheduled market-on-close liquidation")
            except (Exception, KeyboardInterrupt) as failure:
                self._mark(end, closing, bar_exposure, (end - timestamp).total_seconds() / 60)
                self.last_timestamp = timestamp
                self.failed = True
                self.events.append({"timestamp": end.isoformat(), "type": "execution_error", "message": str(failure)})
                raise
            self.finished = True
            snapshot = self._mark(end, closing, bar_exposure, (end - timestamp).total_seconds() / 60)
        else:
            snapshot = self._mark(end, closing, bar_exposure, (end - timestamp).total_seconds() / 60)
            error, requested = None, None
            if hasattr(self.policy, "last_audit"):
                self.policy.last_audit = None
            try:
                if self.halt_reason:
                    decision = Decision(weights={symbol: 0 for symbol in self.config.symbols}, reason=f"Trading halted: {self.halt_reason}")
                else:
                    decision = self.policy.decide(Observation(end, {symbol: frame.copy(deep=True) for symbol, frame in self.history.items()}, self.portfolio.snapshot(closing)))
                    decision = Decision.model_validate(decision)
                requested = decision.weights.copy()
                weights = self._weights(decision)
                self.consecutive_errors = 0
                self.pending = (weights, decision.reason)
                reason = decision.reason
            except Exception as failure:
                error, reason = str(failure), "Decision failed; no new target submitted"
                weights = None
                self.consecutive_errors += 1
                if self.consecutive_errors >= self.config.risk.max_consecutive_decision_errors:
                    self.halt_reason = "decision_error_limit"
                    self.events.append({"timestamp": end.isoformat(), "type": self.halt_reason})
                    self.pending = ({symbol: 0 for symbol in self.config.symbols}, "Decision error limit: liquidate at next bar open")
            self.decisions.append({"timestamp": end.isoformat(), "requested_weights": requested, "accepted_weights": weights, "reason": reason, "error": error,
                                   **({"policy_audit": deepcopy(self.policy.last_audit)} if getattr(self.policy, "last_audit", None) else {})})
        logger.info("%s | equity USD %.2f | fills %d%s", end.isoformat(), snapshot["equity"], len(self.portfolio.fills), f" | halt {self.halt_reason}" if self.halt_reason else "")
        self.last_prices, self.last_timestamp = closing, timestamp
        return True

    def result(self):
        status = "complete" if self.finished else "partial"
        if self.halt_reason:
            status = "risk_halted" if self.halt_reason == "daily_loss_limit" else "policy_halted"
        if self.failed:
            status = "execution_error"
        return {"session": self.session.date, "session_open": self.session.open.isoformat(), "session_close": self.session.close.isoformat(),
                "valuation_timestamp": self.equity_rows[-1]["timestamp"] if self.equity_rows else None,
                "strategy_id": self.config.strategy.kind, "strategy_version": self.config.strategy.version,
                "policy_name": getattr(self.policy, "name", type(self.policy).__name__), "status": status, "finished": self.finished, "halt_reason": self.halt_reason, "initial_equity": self.initial_equity,
                "final_equity": self.portfolio.equity(self.last_prices) if self.last_prices else self.initial_equity,
                "holdings": self.portfolio.snapshot(self.last_prices)["positions"] if self.last_prices else {},
                "equity": self.equity_rows, "fills": [asdict(fill) for fill in self.portfolio.fills], "decisions": self.decisions, "events": self.events,
                "prices": {symbol: [{"timestamp": timestamp.isoformat(), **row.to_dict()} for timestamp, row in frame.iterrows()] for symbol, frame in self.history.items()}}

    def replay(self, frames):
        for timestamp in self.session.grid(self.config.minutes):
            self.observe(timestamp, {symbol: frame.loc[timestamp].to_dict() for symbol, frame in frames.items()})
        return self.result()
