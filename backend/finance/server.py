"""Local finance MCP server. Stdout is reserved for MCP messages."""

import math
import re
from datetime import datetime, timedelta, timezone

import yfinance as yf
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field
from typing import Annotated

yf.config.debug.hide_exceptions = False

mcp = MCPServer("assistant-finance", version="1.0.0")


def normalize_symbol(symbol: str) -> str:
    symbol = symbol.strip().upper()
    if symbol.endswith(".US"):
        symbol = symbol[:-3]
    if not re.fullmatch(r"[A-Z0-9^][A-Z0-9.^=\-]{0,19}", symbol):
        raise ToolError("Provide a valid Yahoo Finance ticker symbol.")
    return symbol


@mcp.tool()
def search_stocks(query: Annotated[str, Field(min_length=1, max_length=200)]) -> dict:
    """Find stock ticker symbols by company name or ticker, using Yahoo Finance."""
    query = query.strip()
    if not query:
        raise ToolError("Search query cannot be blank.")
    try:
        results = yf.Search(query, max_results=5, news_count=0, timeout=10).quotes
    except Exception as exc:
        raise ToolError(f"Yahoo Finance search failed: {exc}") from exc
    return {"source": "Yahoo Finance via yfinance", "quotes": [
        {"symbol": item["symbol"], "name": item.get("shortname") or item.get("longname") or item["symbol"],
         "exchange": item.get("exchange", "")}
        for item in results if item.get("symbol") and item.get("quoteType") in {"EQUITY", "ETF", "INDEX"}
    ]}


@mcp.tool()
def stock_history(symbol: str, days: Annotated[int, Field(ge=1, le=366)] = 7) -> dict:
    """Return the last requested daily OHLCV bars, unadjusted, for a ticker (1–366 trading observations)."""
    symbol = normalize_symbol(symbol)
    ticker = yf.Ticker(symbol)
    start = datetime.now(timezone.utc) - timedelta(days=max(30, days * 2))
    try:
        frame = ticker.history(start=start.date().isoformat(), interval="1d", auto_adjust=False,
                               actions=False, timeout=10)
        metadata = ticker.get_history_metadata() or {}
    except Exception as exc:
        raise ToolError(f"Yahoo Finance history failed for '{symbol}': {exc}") from exc
    if frame.empty:
        raise ToolError(f"No historical data for '{symbol}'.")
    rows = []
    for stamp, row in frame.tail(days).iterrows():
        values = [float(row[column]) for column in ["Open", "High", "Low", "Close", "Volume"]]
        if not all(math.isfinite(value) for value in values):
            continue
        rows.append({"symbol": symbol, "date": stamp.date().isoformat(), "timestamp": stamp.isoformat(),
                     **dict(zip(["open", "high", "low", "close", "volume"], values))})
    if not rows:
        raise ToolError(f"No valid historical prices for '{symbol}'.")
    return {"symbol": symbol, "currency": metadata.get("currency") or "unknown",
            "exchange": metadata.get("exchangeName") or "unknown",
            "timezone": metadata.get("exchangeTimezoneName") or str(frame.index.tz),
            "source": "Yahoo Finance via yfinance", "adjusted": False, "history": rows}


@mcp.tool()
def stock_quote(symbol: str) -> dict:
    """Return the latest available daily price and change; not a guaranteed real-time quote."""
    result = stock_history(symbol, 2)
    latest = result["history"][-1]
    previous = result["history"][-2] if len(result["history"]) > 1 else None
    change = latest["close"] - previous["close"] if previous else None
    return {key: value for key, value in result.items() if key != "history"} | {
        "price": latest["close"], "date": latest["date"], "timestamp": latest["timestamp"],
        "change": change,
        "percent_change": change / previous["close"] * 100 if previous and previous["close"] else None,
    }


@mcp.tool()
def exchange_rate(from_currency: str, to_currency: str) -> dict:
    """Return a daily reference FX rate: target currency units per one source unit."""
    source, target = from_currency.strip().upper(), to_currency.strip().upper()
    if not all(re.fullmatch(r"[A-Z]{3}", code) for code in [source, target]):
        raise ToolError("Provide three-letter currency codes, such as USD and GBP.")
    if source == target:
        raise ToolError("Source and target currencies are the same; no conversion is needed.")
    quote = stock_quote(f"{source}{target}=X")
    if quote["price"] <= 0:
        raise ToolError("No valid exchange rate is available.")
    return {"from_currency": source, "to_currency": target, "rate": quote["price"],
            "date": quote["date"], "timestamp": quote["timestamp"], "source": quote["source"]}


from package_tools import register_tools

register_tools(mcp, normalize_symbol)

if __name__ == "__main__":
    mcp.run(transport="stdio")
