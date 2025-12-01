import csv
import re
import time
from typing import Dict, List

import requests

COINGECKO_ENDPOINT = "https://api.coingecko.com/api/v3/simple/price"
STOOQ_HISTORY_URL = "https://stooq.com/q/d/l/"
YAHOO_AUTOCOMPLETE_ENDPOINT = "https://query1.finance.yahoo.com/v1/finance/search"
COMMON_COMPANY_TICKERS = {
    "apple": "AAPL",
    "microsoft": "MSFT",
    "google": "GOOGL",
    "alphabet": "GOOGL",
    "amazon": "AMZN",
    "meta": "META",
    "facebook": "META",
    "tesla": "TSLA",
    "nvidia": "NVDA",
    "netflix": "NFLX",
    "ibm": "IBM",
    "intel": "INTC",
    "amd": "AMD",
    "oracle": "ORCL",
    "adobe": "ADBE",
}


class FinanceToolError(Exception):
    """Raised when finance data retrieval fails."""


def get_stock_quote(symbol: str) -> Dict[str, str]:
    if not symbol:
        raise ValueError("symbol cannot be empty.")

    history = _fetch_stooq_history(symbol, days=2)
    latest = history[-1]
    previous = history[-2] if len(history) > 1 else latest

    change = latest["close"] - previous["close"]
    percent = ((change / previous["close"]) * 100) if previous["close"] else 0

    return {
        "symbol": latest["symbol"],
        "price": latest["close"],
        "change": change,
        "percent_change": percent,
        "previous_close": previous["close"],
        "open": latest["open"],
        "high": latest["high"],
        "low": latest["low"],
        "volume": latest["volume"],
        "currency": "USD",
        "exchange": "Stooq",
    }


def get_stock_history(symbol: str, days: int = 7) -> Dict[str, List[Dict[str, float]]]:
    if not symbol:
        raise ValueError("symbol cannot be empty.")

    history = _fetch_stooq_history(symbol, days=days)
    return {"symbol": history[-1]["symbol"], "history": history}


def get_crypto_price(coin_id: str, vs_currency: str = "usd") -> Dict[str, str]:
    if not coin_id:
        raise ValueError("coin_id cannot be empty.")

    response = requests.get(
        COINGECKO_ENDPOINT,
        params={"ids": coin_id, "vs_currencies": vs_currency},
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()

    price_info = data.get(coin_id.lower())
    if not price_info:
        raise FinanceToolError(f"Coin '{coin_id}' not found on CoinGecko.")

    return {
        "coin": coin_id.lower(),
        "vs_currency": vs_currency.lower(),
        "price": price_info.get(vs_currency.lower()),
        "source": "CoinGecko",
    }


def lookup_stock_symbols(query: str) -> List[str]:
    if not query or not query.strip():
        return []

    symbols: List[str] = []
    seen = set()

    def add_symbol(sym: str):
        sym = sym.upper()
        if sym and sym not in seen:
            seen.add(sym)
            symbols.append(sym)

    # Match common company names first
    for word in re.findall(r"[A-Za-z]{3,}", query.lower()):
        ticker = COMMON_COMPANY_TICKERS.get(word)
        if ticker:
            add_symbol(ticker)

    # Capture explicit tickers in the query (e.g., AAPL, MSFT)
    for match in re.finditer(r"\b[A-Z]{2,5}\b", query):
        add_symbol(match.group(0))

    try:
        response = requests.get(
            YAHOO_AUTOCOMPLETE_ENDPOINT,
            params={"q": query, "quotesCount": 5, "newsCount": 0},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        for quote in data.get("quotes", []):
            symbol = quote.get("symbol")
            exchange = quote.get("exchange")
            if symbol and exchange and symbol.isupper():
                add_symbol(symbol)
    except Exception:
        pass

    return symbols


def _fetch_stooq_history(symbol: str, days: int) -> List[Dict[str, float]]:
    normalized = _normalize_symbol(symbol)
    try:
        response = _request_with_retry(
            STOOQ_HISTORY_URL,
            params={"s": normalized, "i": "d"},
        )
    except FinanceToolError:
        raise FinanceToolError(f"Failed to fetch history for '{symbol}'.")

    reader = csv.DictReader(response.text.splitlines())
    rows = []
    for row in reader:
        try:
            rows.append(
                {
                    "symbol": symbol.upper(),
                    "date": row["Date"],
                    "open": float(row["Open"]),
                    "high": float(row["High"]),
                    "low": float(row["Low"]),
                    "close": float(row["Close"]),
                    "volume": float(row["Volume"]),
                }
            )
        except (ValueError, KeyError):
            continue

    if not rows:
        raise FinanceToolError(f"No historical data for '{symbol}'.")

    return rows[-max(1, days):]


def _normalize_symbol(symbol: str) -> str:
    symbol = symbol.lower()
    if "." not in symbol:
        symbol = f"{symbol}.us"
    return symbol


def _request_with_retry(url: str, params: Dict[str, str], retries: int = 2):
    last_exc = None
    for attempt in range(retries + 1):
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response
        except Exception as exc:  # pylint: disable=broad-except
            last_exc = exc
            time.sleep(0.5 * (attempt + 1))
    raise FinanceToolError(str(last_exc))
