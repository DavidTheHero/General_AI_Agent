"""Validated configuration shared by replay and polling modes."""
from pathlib import Path
from typing import Literal
import json

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False, strict=True)


class StrategyConfig(Settings):
    kind: Literal["sma", "momentum", "buy_and_hold", "ollama", "trend_following", "mean_reversion", "opening_range_breakout"] = "sma"
    version: Literal["1.0.0"] = "1.0.0"
    fast_window: int = Field(default=3, ge=1, le=100)
    slow_window: int = Field(default=12, ge=2, le=500)
    momentum_threshold: float = Field(default=0.001, ge=0, le=1)
    target_gross_weight: float = Field(default=0.9, ge=0, le=1)
    entry_z: float = Field(default=1.5, gt=0, le=10)
    exit_z: float = Field(default=0.25, ge=0, le=10)
    opening_range_bars: int = Field(default=3, ge=1, le=100)
    model: str = Field(default="llama3.1:8b-instruct-q4_K_M", min_length=1, max_length=120)
    ollama_host: str = "http://localhost:11434"
    model_timeout_seconds: float = Field(default=30, ge=1, le=120)

    @model_validator(mode="after")
    def ordered_windows(self):
        if self.kind in {"sma", "trend_following"} and self.fast_window >= self.slow_window:
            raise ValueError("fast_window must be smaller than slow_window")
        if self.kind == "mean_reversion" and self.exit_z >= self.entry_z:
            raise ValueError("exit_z must be smaller than entry_z")
        if not self.ollama_host.startswith(("http://", "https://")):
            raise ValueError("ollama_host must be an HTTP(S) URL")
        return self


class RiskConfig(Settings):
    max_position_weight: float = Field(default=0.5, gt=0, le=1)
    daily_loss_limit: float = Field(default=0.05, gt=0, le=1)
    max_consecutive_decision_errors: int = Field(default=3, ge=1, le=20)


class CostConfig(Settings):
    commission_bps: float = Field(default=1, ge=0, le=1000)
    slippage_bps: float = Field(default=2, ge=0, le=1000)
    fixed_fee: float = Field(default=0, ge=0, le=1000)


class AgentConfig(Settings):
    symbols: list[str] = Field(default_factory=lambda: ["SPY", "AAPL"], min_length=1, max_length=10)
    interval: Literal["1m", "2m", "5m", "15m", "30m", "60m"] = "5m"
    initial_cash: float = Field(default=100000, gt=0, le=1e12)
    currency: Literal["USD"] = "USD"
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    costs: CostConfig = Field(default_factory=CostConfig)
    poll_seconds: float = Field(default=60, ge=1, le=3600)
    data_lag_seconds: float = Field(default=900, ge=0, le=3600)
    close_grace_seconds: float = Field(default=300, ge=0, le=3600)
    max_data_errors: int = Field(default=3, ge=1, le=20)

    @field_validator("symbols")
    @classmethod
    def valid_symbols(cls, values):
        import re
        symbols = [value.strip().upper() for value in values]
        if any(not re.fullmatch(r"[A-Z0-9^][A-Z0-9.^=_-]{0,19}", value) for value in symbols):
            raise ValueError("Use explicit Yahoo Finance tickers")
        if len(set(symbols)) != len(symbols):
            raise ValueError("Use distinct tickers")
        return symbols

    @property
    def minutes(self):
        return int(self.interval[:-1])


def load_config(path: str | Path | None = None) -> AgentConfig:
    return AgentConfig.model_validate(json.loads(Path(path).read_text(encoding="utf-8")) if path else {})
