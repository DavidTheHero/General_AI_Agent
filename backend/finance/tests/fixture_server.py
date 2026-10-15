"""Real MCP server with fake Yahoo data for offline protocol tests."""

import sys
import time
import asyncio
from types import SimpleNamespace
from pathlib import Path

import pandas as pd
from yfinance.scrapers.history import HistoryMetadata

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


class FakeTicker:
    def __init__(self, symbol):
        self.symbol = symbol

    def __getattr__(self, name):
        if name == "funds_data":
            return SimpleNamespace(**{key: {"dataset": key} for key in ["description", "quote_type", "fund_overview", "fund_operations", "asset_classes", "top_holdings", "equity_holdings", "bond_holdings", "bond_ratings", "sector_weightings"]})
        if name == "option_chain":
            return lambda **kwargs: SimpleNamespace(calls=pd.DataFrame({"strike": [100, 110]}), puts=pd.DataFrame({"strike": [90]}), underlying={"symbol": self.symbol})
        if name.startswith("get_"):
            return lambda **kwargs: {"dataset": name, "arguments": kwargs, "symbol": self.symbol}
        return {"dataset": name, "symbol": self.symbol}

    def history(self, **kwargs):
        if self.symbol == "SLOW":
            time.sleep(2)
        if self.symbol == "EMPTY":
            return pd.DataFrame()
        if self.symbol == "FAIL":
            raise RuntimeError("Yahoo unavailable")
        if self.symbol == "USDGBP=X":
            return pd.DataFrame({"Open": [.75, .75], "High": [.75, .75], "Low": [.75, .75], "Close": [.75, .75], "Volume": [0, 0]}, index=pd.date_range("2026-01-01", periods=2, tz="UTC"))
        return pd.DataFrame({"Open": [100, 105], "High": [110, 120], "Low": [99, 104],
                             "Close": [105, 115], "Volume": [100, 200]},
                            index=pd.date_range("2026-01-01", periods=2, tz="America/New_York"))

    def get_history_metadata(self):
        return HistoryMetadata(SimpleNamespace(_history_metadata={"currency": "USD", "exchangeName": "NMS", "exchangeTimezoneName": "America/New_York", "tradingPeriods": []}))


class FakeSearch:
    def __init__(self, query, **kwargs):
        self.news = [{"title": "Example news"}]
        self.lists = self.nav = self.research = self.all = [{"query": query}]
        self.quotes = [{"symbol": "TTWO", "shortname": "Take-Two Interactive", "exchange": "NMS", "quoteType": "EQUITY"}]


server.yf.Ticker = FakeTicker
server.yf.Search = FakeSearch


class FakeLookup:
    def __init__(self, query, **kwargs):
        self.query = query

    def __getattr__(self, name):
        return lambda count: pd.DataFrame({"symbol": ["NVDA"], "category": [name]})


class FakeCalendars:
    def __init__(self, **kwargs):
        self.window = kwargs

    def __getattr__(self, name):
        return lambda **kwargs: {"dataset": name, "window": self.window, **kwargs}


class FakeSocket:
    def __init__(self, **kwargs):
        self.symbols = []

    async def subscribe(self, symbols):
        self.symbols = symbols

    async def listen(self, callback):
        if "QUIET" in self.symbols:
            await asyncio.sleep(1000)
        for price in [100, 101]:
            callback({"id": self.symbols[0], "price": price})

    async def close(self):
        pass


server.yf.Lookup = FakeLookup
server.yf.Calendars = FakeCalendars
server.yf.Market = lambda market, **kwargs: SimpleNamespace(summary={"market": market}, status=None)
server.yf.Sector = lambda key, **kwargs: SimpleNamespace(**{field: {"key": key} for field in ["name", "symbol", "overview", "research_reports", "top_companies", "industries", "top_etfs", "top_mutual_funds"]})
server.yf.Industry = lambda key, **kwargs: SimpleNamespace(**{field: {"key": key} for field in ["name", "symbol", "overview", "research_reports", "sector_key", "sector_name", "top_companies", "top_growth_companies", "top_performing_companies"]})
server.yf.download = lambda symbols, **kwargs: pd.DataFrame([[100, float("nan")], [101, 200]], columns=pd.MultiIndex.from_tuples([("Close", symbols[0]), ("Close", symbols[-1])]))
server.yf.screen = lambda query, **kwargs: {"query": query if isinstance(query, str) else query.to_dict(), "arguments": kwargs}
server.yf.AsyncWebSocket = FakeSocket

if __name__ == "__main__":
    server.mcp.run(transport="stdio")
