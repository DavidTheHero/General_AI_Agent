"""Agent memory helpers for persisting conversational context."""

from __future__ import annotations

import copy
import datetime as dt
from typing import Any, Dict, List, Optional

MAX_RECENT_SYMBOLS = 8
MAX_STOCK_COMPARISONS = 5
MAX_FACT_ENTRIES = 10

_MEMORY_TEMPLATE: Dict[str, Any] = {
    "stock_context": {
        "last_comparison": None,
        "comparison_history": [],
        "recent_symbols": [],
    },
    "weather_context": {
        "last_location": None,
        "last_conditions": None,
        "last_updated": None,
    },
    "fact_context": {
        "recent_facts": [],
    },
    "time_context": {
        "last_timezone_request": None,
        "last_time_result": None,
        "last_conversion": None,
    },
    "user_profile": {},
}


def _utcnow_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def default_memory() -> Dict[str, Any]:
    """Return a deep copy of the default memory structure."""
    return copy.deepcopy(_MEMORY_TEMPLATE)


def _deep_merge(base: Dict[str, Any], incoming: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    result = copy.deepcopy(base)
    if not incoming:
        return result
    for key, value in incoming.items():
        if key not in result:
            result[key] = copy.deepcopy(value)
            continue
        if isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


class AgentMemory:
    """Structured accessor for agent memory blocks."""

    def __init__(self, initial: Optional[Dict[str, Any]] = None):
        self._data = _deep_merge(default_memory(), initial or {})

    def snapshot(self) -> Dict[str, Any]:
        """Return a deep copy of the current memory map."""
        return copy.deepcopy(self._data)

    # Stock helpers -----------------------------------------------------
    def get_recent_stock_symbols(self) -> List[str]:
        return list(self._data["stock_context"]["recent_symbols"])

    def last_stock_comparison(self) -> Optional[Dict[str, Any]]:
        return self._data["stock_context"].get("last_comparison")

    def remember_stock_symbols(self, symbols: List[str]) -> None:
        context = self._data["stock_context"]
        recent = context["recent_symbols"]
        for symbol in symbols:
            symbol = (symbol or "").upper()
            if not symbol:
                continue
            if symbol in recent:
                recent.remove(symbol)
            recent.append(symbol)
        context["recent_symbols"] = recent[-MAX_RECENT_SYMBOLS:]

    def remember_stock_comparison(self, entries: List[Dict[str, Any]], days: int) -> None:
        context = self._data["stock_context"]
        timestamp = _utcnow_iso()
        record = {
            "entries": entries,
            "days": days,
            "timestamp": timestamp,
            "symbols": [entry.get("symbol") for entry in entries],
        }
        context["last_comparison"] = record
        history = context.setdefault("comparison_history", [])
        history.append(record)
        context["comparison_history"] = history[-MAX_STOCK_COMPARISONS:]
        self.remember_stock_symbols(record["symbols"])

    def remember_stock_quote(self, symbol: str) -> None:
        self.remember_stock_symbols([symbol])

    # Weather helpers ---------------------------------------------------
    def remember_weather(self, location: Dict[str, Any], weather: Dict[str, Any]) -> None:
        context = self._data["weather_context"]
        context["last_location"] = {
            "name": location.get("name"),
            "country": location.get("country"),
            "latitude": location.get("latitude"),
            "longitude": location.get("longitude"),
        }
        context["last_conditions"] = {
            "temperature_c": weather.get("temperature_c"),
            "windspeed_kmh": weather.get("windspeed_kmh"),
            "winddirection": weather.get("winddirection"),
            "time": weather.get("time"),
            "weathercode": weather.get("weathercode"),
        }
        context["last_updated"] = _utcnow_iso()

    # Fact helpers ------------------------------------------------------
    def remember_fact(
        self,
        topic: str,
        answer: str,
        source: Optional[str] = None,
        url: Optional[str] = None,
    ) -> None:
        context = self._data["fact_context"]
        facts = context.setdefault("recent_facts", [])
        facts.append(
            {
                "topic": topic,
                "answer": answer,
                "source": source,
                "url": url,
                "timestamp": _utcnow_iso(),
            }
        )
        context["recent_facts"] = facts[-MAX_FACT_ENTRIES:]

    # Time helpers ------------------------------------------------------
    def remember_time_request(self, timezone: str, payload: Dict[str, Any]) -> None:
        context = self._data["time_context"]
        context["last_timezone_request"] = timezone
        context["last_time_result"] = payload

    def remember_time_conversion(
        self,
        details: Dict[str, Any],
    ) -> None:
        context = self._data["time_context"]
        context["last_conversion"] = details

    # User profile helpers ----------------------------------------------
    def update_user_profile(self, updates: Dict[str, Any]) -> None:
        profile = self._data.setdefault("user_profile", {})
        profile.update(updates)


__all__ = ["AgentMemory", "default_memory"]
