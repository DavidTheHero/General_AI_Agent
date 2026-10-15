"""Policies see only completed bars. They propose weights; the host owns execution."""
from dataclasses import dataclass
import json
from typing import Annotated, Protocol
from urllib.request import Request, urlopen

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from .config import StrategyConfig


@dataclass(frozen=True)
class Observation:
    timestamp: pd.Timestamp
    history: dict[str, pd.DataFrame]
    portfolio: dict


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, revalidate_instances="always")
    weights: dict[str, Annotated[float, Field(strict=True, ge=0, le=1)]]
    reason: str = Field(min_length=1, max_length=500)


class Policy(Protocol):
    def decide(self, observation: Observation) -> Decision: ...


class RulePolicy:
    def __init__(self, config: StrategyConfig):
        self.config = config
        self.name = config.kind

    def decide(self, observation):
        active = []
        for symbol, history in observation.history.items():
            close = history.Close
            if self.config.kind == "buy_and_hold":
                active.append(symbol)
            elif len(close) >= self.config.slow_window:
                if self.config.kind == "sma":
                    signal = close.iloc[-self.config.fast_window:].mean() > close.iloc[-self.config.slow_window:].mean()
                else:
                    signal = close.iloc[-1] / close.iloc[-self.config.slow_window] - 1 > self.config.momentum_threshold
                if signal:
                    active.append(symbol)
        weight = self.config.target_gross_weight / len(active) if active else 0
        return Decision(weights={symbol: weight if symbol in active else 0 for symbol in observation.history},
                        reason=f"{self.config.kind}: {len(active)} active instruments; completed bars only")


class OllamaPolicy:
    def __init__(self, config: StrategyConfig, transport=None):
        self.config = config
        self.transport = transport or self._request
        self.name = f"ollama:{config.model}"

    def _request(self, payload):
        request = Request(f"{self.config.ollama_host.rstrip('/')}/api/chat", data=json.dumps(payload).encode(),
                          headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=self.config.model_timeout_seconds) as response:
            return json.load(response)

    def decide(self, observation):
        symbols = list(observation.history)
        schema = {"type": "object", "properties": {
            "weights": {"type": "object", "properties": {symbol: {"type": "number", "minimum": 0, "maximum": 1} for symbol in symbols}, "required": symbols, "additionalProperties": False},
            "reason": {"type": "string", "maxLength": 500}}, "required": ["weights", "reason"], "additionalProperties": False}
        per_symbol = min(self.config.slow_window, max(1, 60 // len(symbols)))
        features = {}
        for symbol, frame in observation.history.items():
            window = frame.Close.tail(self.config.slow_window)
            features[symbol] = {"window_bars": len(window), "first_close": float(window.iloc[0]), "latest_close": float(window.iloc[-1]),
                                "mean_close": float(window.mean()), "return_pct": float((window.iloc[-1] / window.iloc[0] - 1) * 100)}
        evidence = {"timestamp": observation.timestamp.isoformat(), "portfolio": observation.portfolio,
                    "window_features": features, "recent_bar_limit_per_symbol": per_symbol,
                    "bars": {symbol: [{"timestamp": timestamp.isoformat(), **row.to_dict()} for timestamp, row in frame.tail(per_symbol).iterrows()]
                             for symbol, frame in observation.history.items()}}
        result = self.transport({"model": self.config.model, "stream": False, "format": schema,
            "options": {"temperature": 0, "num_ctx": 8192, "num_predict": 512}, "messages": [
                {"role": "system", "content": "You are a paper-trading allocation policy. Use only the supplied completed bars and portfolio. Return a long-only target weight for EVERY listed symbol; total weights must not exceed 1. Never invent prices or trade unsupported symbols. Prefer cash when evidence is weak. Provide a concise decision description, not private reasoning. The host applies risk limits and fills at a later bar; these are simulations, not broker orders."},
                {"role": "user", "content": json.dumps(evidence)}]})
        return Decision.model_validate_json(result["message"]["content"])


def make_policy(config: StrategyConfig) -> Policy:
    return OllamaPolicy(config) if config.kind == "ollama" else RulePolicy(config)
