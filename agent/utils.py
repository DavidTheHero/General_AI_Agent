"""Utility helpers shared across agent modules."""

from __future__ import annotations

import re
from typing import List

from tools.finance import lookup_stock_symbols


def normalize_location_text(location: str) -> str:
    """Remove common instruction prefixes/suffixes the LM might append."""
    cleaned = (location or "").strip()
    for separator in ("\n", "###", "System:", "User:"):
        if separator in cleaned:
            cleaned = cleaned.split(separator)[0].strip()
    return cleaned.strip(",. ")


def split_queries(text: str) -> List[str]:
    """Split a combined prompt into individual questions/statements."""
    if not text:
        return []

    segments = [
        segment.strip(" ,\n")
        for segment in re.split(r"[?!.]+", text)
        if segment.strip(" ,\n")
    ]
    return segments or [text.strip()]


def extract_stock_symbols(raw: str | None, query: str) -> List[str]:
    symbols = []
    seen = set()
    seed = f"{raw or ''} {query}".strip()
    for symbol in lookup_stock_symbols(seed):
        if symbol not in seen:
            seen.add(symbol)
            symbols.append(symbol)
    return symbols


def extract_days(text: str, default: int = 7) -> int:
    match = re.search(r"(\d+)\s*(day|week)", text, re.IGNORECASE)
    if match:
        value = int(match.group(1))
        unit = match.group(2).lower()
        if "week" in unit:
            return value * 7
        return value
    return default
