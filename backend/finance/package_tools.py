"""Validated MCP operations covering yfinance's public data capabilities."""

import asyncio
import json
import math
from collections.abc import KeysView, ValuesView, Mapping
from datetime import date, datetime, timezone
from typing import Annotated, Any, Literal

import numpy as np
import pandas as pd
import yfinance as yf
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

Limit = Annotated[int, Field(ge=1, le=500)]
Symbols = Annotated[list[str], Field(min_length=1, max_length=10)]
Text = Annotated[str, Field(min_length=1, max_length=200)]
Region = Annotated[str, Field(pattern=r"^[A-Z]{2,10}$")]
Interval = Literal["1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h", "1d", "5d", "1wk", "1mo", "3mo"]
Period = Literal["1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"]
TickerDataset = Literal[
    "info", "fast_info", "isin", "history_metadata", "actions", "dividends", "splits", "capital_gains",
    "shares", "shares_full", "news", "calendar", "earnings_dates", "sec_filings", "income_stmt",
    "balance_sheet", "cash_flow", "earnings", "recommendations", "recommendations_summary",
    "upgrades_downgrades", "sustainability", "analyst_price_targets", "earnings_estimate", "revenue_estimate",
    "earnings_history", "eps_trend", "eps_revisions", "growth_estimates", "insider_purchases",
    "insider_transactions", "insider_roster_holders", "major_holders", "institutional_holders",
    "mutualfund_holders", "valuation", "options",
]
FundDataset = Literal["description", "quote_type", "fund_overview", "fund_operations", "asset_classes",
                      "top_holdings", "equity_holdings", "bond_holdings", "bond_ratings", "sector_weightings"]


def result(value: Any, limit: int = 100) -> dict:
    """Preserve table axes and nulls; explicitly report bounded output truncation."""
    truncated = False

    def clean(item, depth=0):
        nonlocal truncated
        if depth > 12:
            raise ToolError("Result is too deeply nested to serialize.")
        if isinstance(item, pd.DataFrame):
            truncated |= len(item) > limit or len(item.columns) > 100
            frame = item.iloc[:limit, :100]
            return {"columns": [clean(column, depth + 1) for column in frame.columns],
                    "index": [clean(index, depth + 1) for index in frame.index],
                    "rows": [[clean(cell, depth + 1) for cell in row] for row in frame.itertuples(index=False, name=None)]}
        if isinstance(item, pd.Series):
            return clean(item.to_frame(), depth + 1)
        if isinstance(item, (datetime, date)):
            return item.isoformat()
        if isinstance(item, np.generic):
            return clean(item.item(), depth + 1)
        if item is None or item is pd.NA or item is pd.NaT:
            return None
        if isinstance(item, float):
            return item if math.isfinite(item) else None
        if isinstance(item, (str, int, bool)):
            return item
        if isinstance(item, Mapping):
            truncated |= len(item) > 500
            return {str(key): clean(value, depth + 1) for key, value in list(item.items())[:500]}
        if isinstance(item, (KeysView, ValuesView)):
            item = list(item)
        if isinstance(item, (set, frozenset)):
            item = sorted(item)
        if isinstance(item, (list, tuple)):
            truncated |= len(item) > limit
            return [clean(value, depth + 1) for value in item[:limit]]
        raise ToolError(f"Unsupported result type: {type(item).__name__}")

    payload = {"source": "Yahoo Finance via yfinance", "retrieved_at": datetime.now(timezone.utc).isoformat(),
               "data": clean(value), "truncated": truncated}
    if len(json.dumps(payload, allow_nan=False).encode()) > 256000:
        raise ToolError("Result exceeds 256 KB; reduce limit or select a narrower dataset.")
    return payload


def date_window(start: str | None, end: str | None):
    try:
        first = date.fromisoformat(start) if start else None
        last = date.fromisoformat(end) if end else None
    except ValueError as exc:
        raise ToolError("Use ISO dates: YYYY-MM-DD.") from exc
    if last and not first:
        raise ToolError("Provide start when using end.")
    if first and last and first >= last:
        raise ToolError("start must be before end; end is exclusive.")


def invoke(work, limit=100):
    try:
        return result(work(), limit)
    except ToolError:
        raise
    except Exception as exc:
        raise ToolError(f"yfinance request failed: {exc}") from exc


def register_tools(mcp, normalize_symbol):
    @mcp.resource("yfinance://capabilities")
    def capabilities() -> str:
        """Installed package coverage, equivalent operations, and server boundaries."""
        return json.dumps({
            "version": yf.__version__,
            "coverage": {
                "Ticker": "ticker_data, price_history, option_chain, stock_quote, stock_history, exchange_rate",
                "Tickers/download": "download_prices; ticker_data per symbol for other datasets",
                "Search": "search_finance, search_stocks",
                "Lookup": "lookup_instruments",
                "Market/MarketRegion": "market_data",
                "Calendars": "calendar_events",
                "FundsData": "fund_data",
                "Sector/Industry": "sector_data, industry_data",
                "EquityQuery/FundQuery/ETFQuery/screen/PREDEFINED_SCREENER_QUERIES": "screener_catalog, screen_instruments",
                "WebSocket/AsyncWebSocket/Ticker.live/Tickers.live": "stream_prices: finite snapshot via AsyncWebSocket",
            },
            "aliases": "get_* and property aliases share datasets; financials/incomestmt map to income_stmt; balancesheet to balance_sheet; cashflow to cash_flow. Frequency selects annual/quarterly/trailing statements.",
            "administrative_exclusions": {
                "Auth": "Authentication/session management stays server-side; credentials are not returned as MCP data.",
                "config/set_config/enable_debug_mode/set_tz_cache_location": "Deployment settings stay server-side; tools do not change filesystem paths or global configuration.",
            },
            "bounds": {"symbols": 10, "rows": 500, "columns": 100, "result_bytes": 256000, "stream_seconds": 10},
        })

    @mcp.tool()
    def ticker_data(symbol: str, dataset: TickerDataset, frequency: Literal["yearly", "quarterly", "trailing"] = "yearly",
                    start: str | None = None, end: str | None = None, limit: Limit = 100) -> dict:
        """Read one ticker dataset: fundamentals, statements, corporate actions, news, estimates, holders, options expiries, or valuation. Missing values remain null. Tables retain axes."""
        date_window(start, end)
        ticker = yf.Ticker(normalize_symbol(symbol))
        def read():
            if dataset in {"income_stmt", "balance_sheet", "cash_flow"}:
                return getattr(ticker, f"get_{dataset}")(freq=frequency)
            if dataset == "earnings":
                if frequency == "trailing":
                    raise ToolError("Legacy earnings supports yearly or quarterly frequency.")
                return ticker.get_earnings(freq=frequency)
            if dataset == "shares_full":
                return ticker.get_shares_full(start=start, end=end)
            if dataset == "news":
                return ticker.get_news(count=min(limit, 100))
            if dataset == "earnings_dates":
                return ticker.get_earnings_dates(limit=min(limit, 100))
            if dataset == "valuation":
                return ticker.get_valuation_measures(freq="quarterly" if frequency == "quarterly" else "yearly", periods=min(limit, 20))
            if dataset == "fast_info":
                return dict(ticker.fast_info)
            return getattr(ticker, dataset)
        return invoke(read, limit)

    @mcp.tool()
    def price_history(symbol: str, period: Period = "1mo", interval: Interval = "1d", start: str | None = None,
                      end: str | None = None, adjusted: bool = False, prepost: bool = False,
                      actions: bool = True, repair: bool = False, back_adjust: bool = False, keepna: bool = False,
                      rounding: bool = False, limit: Limit = 100) -> dict:
        """Get daily or intraday history with explicit adjustment and session options. Dates override period; Yahoo intraday retention limits apply. end is exclusive."""
        date_window(start, end)
        ticker = yf.Ticker(normalize_symbol(symbol))
        return invoke(lambda: {"symbol": normalize_symbol(symbol), "adjusted": adjusted, "interval": interval,
                              "prices": ticker.history(period=None if start else period, start=start, end=end, interval=interval,
                                                       auto_adjust=adjusted, prepost=prepost, actions=actions, repair=repair,
                                                       back_adjust=back_adjust, keepna=keepna, rounding=rounding, timeout=10),
                              "metadata": ticker.get_history_metadata()}, limit)

    @mcp.tool()
    def download_prices(symbols: Symbols, period: Period = "1mo", interval: Interval = "1d",
                        start: str | None = None, end: str | None = None, adjusted: bool = False,
                        actions: bool = False, prepost: bool = False, repair: bool = False, back_adjust: bool = False,
                        keepna: bool = False, rounding: bool = False, ignore_tz: bool | None = None, limit: Limit = 100) -> dict:
        """Batch download up to ten tickers, retaining multi-level columns, missing values and dates. Equivalent to Tickers.history/download without a persistent object."""
        date_window(start, end)
        normalized = [normalize_symbol(symbol) for symbol in symbols]
        return invoke(lambda: {"symbols": normalized, "adjusted": adjusted, "interval": interval,
                              "prices": yf.download(normalized, period=None if start else period, start=start, end=end,
                                                    interval=interval, auto_adjust=adjusted, actions=actions, prepost=prepost,
                                                    repair=repair, back_adjust=back_adjust, keepna=keepna, rounding=rounding, ignore_tz=ignore_tz,
                                                    threads=False, progress=False, timeout=10)}, limit)

    @mcp.tool()
    def search_finance(query: Text, dataset: Literal["quotes", "news", "lists", "nav", "research", "all"] = "quotes", limit: Annotated[int, Field(ge=1, le=25)] = 10) -> dict:
        """Search Yahoo instruments, news, lists, navigation and research data, not only stocks."""
        return invoke(lambda: getattr(yf.Search(query, max_results=limit, news_count=limit, lists_count=limit,
                                               include_nav_links=True, include_research=True, timeout=10), dataset), limit)

    @mcp.tool()
    def lookup_instruments(query: Text, category: Literal["all", "stock", "etf", "mutualfund", "index", "future", "currency", "cryptocurrency"] = "all", limit: Annotated[int, Field(ge=1, le=100)] = 25) -> dict:
        """Look up instruments by asset class, including currencies, futures and cryptocurrencies."""
        return invoke(lambda: getattr(yf.Lookup(query, timeout=10), f"get_{category}")(count=limit), limit)

    @mcp.tool()
    def market_data(market: Literal["US", "GB", "ASIA", "EUROPE", "RATES", "COMMODITIES", "CURRENCIES", "CRYPTOCURRENCIES"] = "US", dataset: Literal["summary", "status"] = "summary", limit: Limit = 100) -> dict:
        """Retrieve regional market summary or status. Yahoo status may be unavailable for non-US regions; it is not synthesized."""
        return invoke(lambda: getattr(yf.Market(market, timeout=10), dataset), limit)

    @mcp.tool()
    def calendar_events(dataset: Literal["earnings", "economic_events", "ipo_info", "splits"], start: str, end: str,
                        limit: Annotated[int, Field(ge=1, le=100)] = 25, offset: Annotated[int, Field(ge=0, le=10000)] = 0) -> dict:
        """Retrieve a paginated earnings, economic, IPO or split calendar for an ISO date window of up to 31 days."""
        date_window(start, end)
        if (date.fromisoformat(end) - date.fromisoformat(start)).days > 31:
            raise ToolError("Calendar windows cannot exceed 31 days.")
        return invoke(lambda: getattr(yf.Calendars(start=start, end=end), f"get_{dataset}_calendar")(limit=limit, offset=offset), limit)

    @mcp.tool()
    def fund_data(symbol: str, dataset: FundDataset, limit: Limit = 100) -> dict:
        """Retrieve fund/ETF overview, operations, asset allocation, top holdings, bond ratings or sector weights."""
        return invoke(lambda: getattr(yf.Ticker(normalize_symbol(symbol)).funds_data, dataset), limit)

    @mcp.tool()
    def sector_data(key: Text, dataset: Literal["name", "symbol", "overview", "research_reports", "top_companies", "industries", "top_etfs", "top_mutual_funds"] = "overview", region: Region = "US", limit: Limit = 100) -> dict:
        """Read sector metadata, industries, companies or funds using a Yahoo sector slug such as technology."""
        return invoke(lambda: getattr(yf.Sector(key, region=region), dataset), limit)

    @mcp.tool()
    def industry_data(key: Text, dataset: Literal["name", "symbol", "overview", "research_reports", "sector_key", "sector_name", "top_companies", "top_growth_companies", "top_performing_companies"] = "overview", region: Region = "US", limit: Limit = 100) -> dict:
        """Read industry metadata and leading companies using a Yahoo industry slug such as semiconductors."""
        return invoke(lambda: getattr(yf.Industry(key, region=region), dataset), limit)

    @mcp.tool()
    def option_chain(symbol: str, expiry: str | None = None, limit: Limit = 100) -> dict:
        """Read call and put option chains for an expiry, or the nearest available expiry. No orders are placed."""
        if expiry:
            try:
                date.fromisoformat(expiry)
            except ValueError as exc:
                raise ToolError("Use YYYY-MM-DD for expiry.") from exc
        def read():
            chain = yf.Ticker(normalize_symbol(symbol)).option_chain(date=expiry)
            return {"calls": chain.calls, "puts": chain.puts, "underlying": chain.underlying}
        return invoke(read, limit)

    @mcp.tool()
    def screener_catalog(asset: Literal["equity", "fund", "etf"] = "equity") -> dict:
        """Discover predefined screeners and valid fields/values for custom EquityQuery, FundQuery or ETFQuery filters."""
        cls = {"equity": yf.EquityQuery, "fund": yf.FundQuery, "etf": yf.ETFQuery}[asset]
        query = cls("gt", ["intradayprice", 0])
        return result({"predefined": list(yf.PREDEFINED_SCREENER_QUERIES), "valid_fields": query.valid_fields, "valid_values": query.valid_values}, 500)

    @mcp.tool()
    def screen_instruments(predefined: str | None = None, query: dict | None = None,
                           asset: Literal["equity", "fund", "etf"] = "equity",
                           limit: Annotated[int, Field(ge=1, le=100)] = 25,
                           offset: Annotated[int, Field(ge=0, le=10000)] = 0,
                           sort_field: str | None = None, ascending: bool = False) -> dict:
        """Run a predefined screener OR a custom JSON query {operator, operands}; and/or operands contain nested query objects. Use screener_catalog to discover fields."""
        if (predefined is None) == (query is None):
            raise ToolError("Provide exactly one of predefined or query.")
        cls = {"equity": yf.EquityQuery, "fund": yf.FundQuery, "etf": yf.ETFQuery}[asset]
        def build(node, depth=0):
            if depth > 5 or not isinstance(node, dict) or set(node) != {"operator", "operands"}:
                raise ToolError("Queries require operator/operands and at most six levels.")
            op, operands = node["operator"], node["operands"]
            if not isinstance(operands, list) or len(operands) > 20:
                raise ToolError("Provide at most 20 operands per query.")
            return cls(op, [build(item, depth + 1) for item in operands] if op in {"and", "or"} else operands)
        def read():
            selected = predefined
            if predefined is not None and predefined not in yf.PREDEFINED_SCREENER_QUERIES:
                raise ToolError("Unknown predefined screener; use screener_catalog.")
            if query is not None:
                selected = build(query)
            return yf.screen(selected, size=limit, offset=offset, sortField=sort_field, sortAsc=ascending)
        return invoke(read, limit)

    @mcp.tool()
    async def stream_prices(symbols: Symbols, seconds: Annotated[int, Field(ge=1, le=10)] = 3,
                            limit: Annotated[int, Field(ge=1, le=100)] = 25) -> dict:
        """Collect a bounded snapshot of Yahoo WebSocket price messages, then unsubscribe and close. No messages may arrive while markets are closed."""
        normalized = [normalize_symbol(symbol) for symbol in symbols]
        messages = []
        done = asyncio.Event()
        socket = yf.AsyncWebSocket(verbose=False)
        def receive(message):
            if len(messages) < limit:
                messages.append(message)
            if len(messages) >= limit:
                done.set()
        listener = None
        try:
            async with asyncio.timeout(seconds):
                await socket.subscribe(normalized)
                listener = asyncio.create_task(socket.listen(receive))
                waiter = asyncio.create_task(done.wait())
                try:
                    await asyncio.wait([listener, waiter], return_when=asyncio.FIRST_COMPLETED)
                    if listener.done():
                        await listener
                finally:
                    waiter.cancel()
                    await asyncio.gather(waiter, return_exceptions=True)
        except TimeoutError:
            pass
        except Exception as exc:
            raise ToolError(f"yfinance stream failed: {exc}") from exc
        finally:
            if listener:
                listener.cancel()
                await asyncio.gather(listener, return_exceptions=True)
            await socket.close()
        return result({"symbols": normalized, "messages": messages, "window_seconds": seconds}, limit)
