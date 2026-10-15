"""Whole-share, cash-only simulated execution with auditable costs and P&L."""
from dataclasses import asdict, dataclass
import math

import pandas as pd

from .config import CostConfig


@dataclass
class Position:
    quantity: int = 0
    average_cost: float = 0


@dataclass(frozen=True)
class Fill:
    timestamp: str
    symbol: str
    side: str
    quantity: int
    reference_price: float
    fill_price: float
    commission: float
    slippage_cost: float
    realized_pnl: float
    reason: str


class Portfolio:
    def __init__(self, cash: float, symbols: list[str], costs: CostConfig):
        if not math.isfinite(cash) or cash < 0:
            raise ValueError("Initial cash must be finite and nonnegative")
        self.cash, self.initial_cash, self.costs = cash, cash, costs
        self.positions = {symbol: Position() for symbol in symbols}
        self.fills: list[Fill] = []

    def equity(self, prices):
        return self.cash + sum(position.quantity * prices[symbol] for symbol, position in self.positions.items())

    def snapshot(self, prices):
        equity = self.equity(prices)
        return {"cash": self.cash, "equity": equity, "positions": {symbol: {**asdict(position), "market_price": prices[symbol],
                "market_value": position.quantity * prices[symbol], "weight": position.quantity * prices[symbol] / equity if equity > 0 else 0}
                for symbol, position in self.positions.items()}}

    def fill(self, timestamp, symbol, side, quantity, price, reason):
        if not isinstance(quantity, int) or isinstance(quantity, bool):
            raise ValueError("Only whole-share quantities are supported")
        if quantity <= 0:
            return None
        if symbol not in self.positions or side not in {"buy", "sell"} or not math.isfinite(price) or price <= 0:
            raise ValueError("Invalid simulated order")
        position = self.positions[symbol]
        rate = self.costs.commission_bps / 10000
        fill_price = price * (1 + (1 if side == "buy" else -1) * self.costs.slippage_bps / 10000)
        if side == "buy":
            affordable = max(0, math.floor((self.cash - self.costs.fixed_fee) / (fill_price * (1 + rate))))
            quantity = min(quantity, affordable)
        else:
            quantity = min(quantity, position.quantity)
        if quantity == 0:
            return None
        notional = quantity * fill_price
        commission = notional * rate + self.costs.fixed_fee
        if side == "sell" and commission > self.cash + notional + 1e-8:
            raise ValueError("Cash cannot cover simulated exit fees")
        realized = 0
        if side == "buy":
            total_cost = position.average_cost * position.quantity + notional + commission
            position.quantity += quantity
            position.average_cost = total_cost / position.quantity
            self.cash -= notional + commission
        else:
            realized = notional - commission - quantity * position.average_cost
            self.cash += notional - commission
            position.quantity -= quantity
            if position.quantity == 0:
                position.average_cost = 0
        if self.cash < -1e-7:
            raise AssertionError("Execution created leverage")
        self.cash = max(self.cash, 0)
        fill = Fill(pd.Timestamp(timestamp).isoformat(), symbol, side, quantity, price, fill_price, commission,
                    quantity * abs(fill_price - price), realized, reason)
        self.fills.append(fill)
        return fill

    def rebalance(self, timestamp, weights, prices, reason):
        equity = self.equity(prices)
        targets = {symbol: math.floor(max(0, weights[symbol]) * equity / prices[symbol]) for symbol in self.positions}
        # Sell first so one target does not use cash earmarked for another position.
        for side in ["sell", "buy"]:
            for symbol, position in self.positions.items():
                delta = targets[symbol] - position.quantity
                if (side == "buy" and delta > 0) or (side == "sell" and delta < 0):
                    self.fill(timestamp, symbol, side, abs(delta), prices[symbol], reason)

    def liquidate(self, timestamp, prices, reason):
        for symbol, position in self.positions.items():
            self.fill(timestamp, symbol, "sell", position.quantity, prices[symbol], reason)
