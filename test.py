"""
Unit tests for finance tools using mocked HTTP responses.

These tests run without network access by patching `requests.get` and
injecting canned JSON payloads that mimic Yahoo Finance / CoinGecko responses.
"""

import sys
import types
import unittest
from unittest.mock import patch


# Provide a minimal `requests` module if it's missing so imports succeed.
if "requests" not in sys.modules:
    dummy_requests = types.ModuleType("requests")

    def _missing(*args, **kwargs):  # pylint: disable=unused-argument
        raise RuntimeError("requests.get called in test without mock")

    dummy_requests.get = _missing  # type: ignore[attr-defined]
    sys.modules["requests"] = dummy_requests


from memory import AgentMemory, default_memory  # noqa: E402
from semantic_memory import SemanticMemoryStore  # noqa: E402
from tools import finance  # noqa: E402


class DummyResponse:
    def __init__(self, payload=None, text=""):
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("No JSON payload")
        return self._payload

    def raise_for_status(self):
        return None


class FinanceToolTests(unittest.TestCase):
    def test_get_stock_quote_parses_fields(self):
        csv_data = (
            "Date,Open,High,Low,Close,Volume\n"
            "2024-11-28,180,182,179,181,1000000\n"
            "2024-11-29,181,184,180,183,1200000\n"
        )

        with patch(
            "tools.finance.requests.get",
            return_value=DummyResponse(text=csv_data),
        ):
            quote = finance.get_stock_quote("AAPL")

        self.assertEqual(quote["symbol"], "AAPL")
        self.assertEqual(quote["price"], 183.0)
        self.assertAlmostEqual(quote["change"], 2.0)
        self.assertEqual(quote["exchange"], "Stooq")

    def test_get_stock_history_computes_series(self):
        csv_data = (
            "Date,Open,High,Low,Close,Volume\n"
            "2024-11-27,170,172,169,171,900000\n"
            "2024-11-28,171,173,170,172,950000\n"
            "2024-11-29,172,175,171,174,980000\n"
        )

        with patch(
            "tools.finance.requests.get",
            return_value=DummyResponse(text=csv_data),
        ):
            history = finance.get_stock_history("MSFT", days=3)

        self.assertEqual(history["symbol"], "MSFT")
        closes = [point["close"] for point in history["history"]]
        self.assertEqual(closes, [171.0, 172.0, 174.0])

    def test_lookup_stock_symbols_prefers_autocomplete(self):
        payload = {
            "quotes": [
                {"symbol": "TSLA", "exchange": "NMS"},
                {"symbol": "MSFT", "exchange": "NMS"},
            ]
        }

        with patch("tools.finance.requests.get", return_value=DummyResponse(payload)):
            symbols = finance.lookup_stock_symbols("compare Tesla with MSFT")

        self.assertIn("TSLA", symbols)
        self.assertIn("MSFT", symbols)


class MemoryTests(unittest.TestCase):
    def test_default_memory_contains_expected_sections(self):
        state = default_memory()
        self.assertIn("stock_context", state)
        self.assertIn("weather_context", state)
        self.assertIn("fact_context", state)

    def test_stock_memory_tracks_recent_symbols(self):
        memory = AgentMemory()
        entries = [
            {"symbol": "AAPL", "start": 150.0, "end": 155.0, "change_pct": 3.33},
            {"symbol": "MSFT", "start": 320.0, "end": 330.0, "change_pct": 3.12},
        ]
        memory.remember_stock_comparison(entries, days=5)
        snapshot = memory.snapshot()
        recent = snapshot["stock_context"]["recent_symbols"]
        self.assertEqual(recent[-2:], ["AAPL", "MSFT"])


class SemanticStoreTests(unittest.TestCase):
    def test_store_records_and_queries(self):
        store = SemanticMemoryStore(":memory:")
        try:
            store.add_entry("session-1", "user", "I love visiting Paris in summer.")
            store.add_entry("session-1", "assistant", "You mentioned travel to France.")
            matches = store.query("session-1", "Paris trip", top_k=2)
            self.assertGreaterEqual(len(matches), 1)
            self.assertTrue(any("Paris" in match["content"] for match in matches))
            store.delete_session("session-1")
            self.assertEqual(store.query("session-1", "Paris", top_k=2), [])
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
