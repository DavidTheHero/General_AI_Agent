"""Versioned strategy descriptions and the configuration validation boundary."""
from copy import deepcopy

from .config import StrategyConfig


_COMMON = ["kind", "version", "target_gross_weight"]
_DEFINITIONS = {
    "trend_following": {
        "hypothesis": "Persistent intraday order flow can produce continuation after a short moving average exceeds a longer moving average.",
        "parameters": ["fast_window", "slow_window"],
        "warmup": "slow_window completed bars within each session; cash before warm-up.",
        "failure_conditions": ["Sideways markets cause repeated whipsaw and costs.", "Intraday trends can reverse before next-open execution."],
    },
    "mean_reversion": {
        "hypothesis": "Temporary intraday selling pressure can reverse toward the recent mean when the latest close is unusually low.",
        "parameters": ["slow_window", "entry_z", "exit_z"],
        "warmup": "slow_window completed bars; population standard deviation uses that window, including latest close.",
        "failure_conditions": ["Persistent downward repricing can defeat reversion.", "Zero-variance windows produce cash targets.", "A held position exits when z >= -exit_z; a flat position enters when z <= -entry_z."],
    },
    "opening_range_breakout": {
        "hypothesis": "A completed close above the initial session range may identify sustained directional demand after opening price discovery.",
        "parameters": ["opening_range_bars"],
        "warmup": "opening_range_bars completed bars define the fixed high; a later completed close must exceed it. Signal then latches until session close.",
        "failure_conditions": ["False breakouts reverse after entry.", "A session with no bars after the opening range cannot enter.", "Aggregated bars cannot establish within-bar execution or quote liquidity."],
    },
    "momentum": {
        "hypothesis": "Positive completed-window price momentum may persist to later intraday bars.",
        "parameters": ["slow_window", "momentum_threshold"],
        "warmup": "slow_window completed bars within each session.",
        "failure_conditions": ["Price reversals and trading costs can erase continuation."],
    },
    "buy_and_hold": {
        "hypothesis": "An equal-weight long allocation provides an executable intraday reference under the same capital, risk and cost constraints.",
        "parameters": [],
        "warmup": "One completed bar; first entry at the second bar open, liquidation at session close.",
        "failure_conditions": ["A falling market loses capital.", "Whole shares, cash and position caps can leave uninvested capital."],
    },
    "ollama": {
        "hypothesis": "An experimental language model may map supplied completed-bar evidence to useful long-only allocations; this is unproven.",
        "parameters": ["slow_window", "model", "ollama_host", "model_timeout_seconds"],
        "warmup": "One completed bar; full slow_window features accumulate during the session.",
        "failure_conditions": ["Historical model training contamination prevents an unbiased historical edge claim.", "Temperature zero does not guarantee deterministic output.", "Timeouts, invalid allocations and unavailable model identity can invalidate an experiment."],
        "experimental": True,
    },
}
_DEFINITIONS["sma"] = {**_DEFINITIONS["trend_following"], "compatibility_alias_for": "trend_following"}


def list_strategies():
    properties = StrategyConfig.model_json_schema()["properties"]
    result = []
    for name, definition in _DEFINITIONS.items():
        fields = _COMMON + definition["parameters"]
        schema = {"type": "object", "additionalProperties": False,
                  "properties": {key: deepcopy(properties[key]) for key in fields}, "required": ["kind"]}
        schema["properties"]["kind"] = {"const": name, "type": "string"}
        result.append({"id": name, "version": "1.0.0", "hypothesis": definition["hypothesis"],
                       "parameters": schema, "required_observations": ["Chronological completed regular-session OHLCV bars", "USD cash and current long holdings"],
                       "warmup": definition["warmup"], "failure_conditions": definition["failure_conditions"],
                       "experimental": definition.get("experimental", False),
                       "prerequisites": ["Simulation only; USD, long-only, whole shares, no borrowing.",
                                         "Shorting requires borrow availability, locate/recall and financing models; leverage requires margin and liquidation models.",
                                         "Trade/quote strategies require timestamped trades/quotes and execution/liquidity models; OHLCV bars are insufficient."],
                       **({"compatibility_alias_for": definition["compatibility_alias_for"]} if "compatibility_alias_for" in definition else {})})
    return deepcopy(result)


def validate_strategy(value):
    config = StrategyConfig.model_validate(value)
    metadata = next(item for item in list_strategies() if item["id"] == config.kind)
    return {"config": config.model_dump(), "metadata": metadata}
