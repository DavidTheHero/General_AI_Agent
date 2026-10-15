"""Explicit, timezone-aware bar ingestion. No price interpolation or forward fill."""
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import logging
from typing import Protocol

import numpy as np
import pandas as pd
import yfinance as yf

from .calendar import Session
from .config import AgentConfig

logger = logging.getLogger(__name__)


class DataError(RuntimeError):
    pass


def validate_yahoo_window(start, end, interval, *, now=None):
    """Reject known unsupported windows; dates are inclusive and exchange-local."""
    first, last = pd.Timestamp(start).date(), pd.Timestamp(end).date()
    if first > last:
        raise DataError("start must not be after end")
    retention = 30 if interval == "1m" else 730 if interval == "60m" else 60
    today = pd.Timestamp(now or datetime.now(timezone.utc)).tz_convert("America/New_York").date()
    earliest = today - timedelta(days=retention)
    if first < earliest:
        raise DataError(f"Yahoo {interval} history is limited to approximately the most recent {retention} days; "
                        f"the requested start {start} is before {earliest.isoformat()}. "
                        "Choose recent dates or 60m bars (approximately 730 days). Older minute data requires a previously saved dataset or another provider. "
                        "Splitting requests cannot recover expired data. Dates and interval were not changed.")


@dataclass
class MarketData:
    frames: dict[str, pd.DataFrame]
    source: str
    retrieved_at: str
    metadata: dict = field(default_factory=dict)


class DataFeed(Protocol):
    def fetch(self, symbols: list[str], start: str, end: str, interval: str) -> MarketData: ...


def normalize_bars(frame: pd.DataFrame) -> pd.DataFrame:
    required = ["Open", "High", "Low", "Close", "Volume"]
    if frame.empty:
        raise DataError("No intraday bars returned")
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None:
        raise DataError("Provider bars must have timezone-aware timestamps")
    if not set(required).issubset(frame.columns):
        raise DataError("Provider bars are missing OHLCV columns")
    result = frame.loc[:, required].copy().astype(float)
    result.index = result.index.tz_convert("UTC")
    result = result.sort_index()
    if result.index.has_duplicates:
        raise DataError("Duplicate provider timestamps")
    return result


def clean_bars(frame: pd.DataFrame) -> pd.DataFrame:
    result = normalize_bars(frame)
    finite = np.isfinite(result.to_numpy()).all(axis=1)
    valid = finite & (result[["Open", "High", "Low", "Close"]] > 0).all(axis=1) & (result.Volume >= 0)
    valid &= (result.High >= result[["Open", "Low", "Close"]].max(axis=1)) & (result.Low <= result[["Open", "High", "Close"]].min(axis=1))
    if not valid.all():
        raise DataError(f"Invalid or missing OHLCV values in {int((~valid).sum())} bars")
    return result


class YahooFinanceFeed:
    def __init__(self, ticker_factory=yf.Ticker, *, clock=None):
        self.ticker_factory = ticker_factory
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def fetch(self, symbols, start, end, interval):
        validate_yahoo_window(start, end, interval, now=self.clock())
        frames, metadata = {}, {}
        # yfinance end is exclusive; the public feed interface uses inclusive dates.
        stop = pd.Timestamp(end).date() + timedelta(days=1)
        cursor, windows = pd.Timestamp(start).date(), []
        while cursor < stop:
            # Seven days stays below Yahoo's eight-day limit even over a DST change.
            boundary = min(cursor + timedelta(days=7), stop) if interval == "1m" else stop
            windows.append((cursor.isoformat(), boundary.isoformat()))
            cursor = boundary
        for symbol in symbols:
            ticker = self.ticker_factory(symbol)
            chunks, requests = [], []
            try:
                for number, (batch_start, batch_end) in enumerate(windows, 1):
                    logger.info("%s: fetching batch %d/%d, %s to %s (exclusive), %s", symbol, number, len(windows), batch_start, batch_end, interval)
                    try:
                        frame = ticker.history(start=batch_start, end=batch_end, interval=interval, auto_adjust=False,
                                               actions=True, prepost=False, timeout=10, raise_errors=True)
                    except Exception as error:
                        raise DataError(f"Yahoo Finance failed for {symbol}, batch {batch_start} to {batch_end} (exclusive): {error}") from error
                    request = {"start": batch_start, "end_exclusive": batch_end, "rows": 0}
                    requests.append(request)
                    if frame.empty:
                        continue  # A final batch can contain only market-closure dates.
                    details = ticker.get_history_metadata() or {}
                    currency = details.get("currency")
                    if currency != "USD":
                        raise DataError(f"{symbol}: expected USD prices, received {currency or 'unknown currency'}; FX simulation is not configured")
                    if "Stock Splits" in frame and (frame["Stock Splits"].fillna(0) != 0).any():
                        raise DataError(f"{symbol}: split detected; select sessions without a split or supply explicitly normalized data")
                    chunk = normalize_bars(frame)
                    lower = pd.Timestamp(batch_start, tz="America/New_York").tz_convert("UTC")
                    upper = pd.Timestamp(batch_end, tz="America/New_York").tz_convert("UTC")
                    chunk = chunk.loc[(chunk.index >= lower) & (chunk.index < upper)]
                    request["rows"] = len(chunk)
                    chunks.append(chunk)
                    metadata[symbol] = {"currency": currency, "exchange": details.get("exchangeName"), "timezone": details.get("exchangeTimezoneName"), "requests": requests}
                frames[symbol] = normalize_bars(pd.concat(chunks) if chunks else pd.DataFrame())
            except DataError:
                raise
            except Exception as error:
                raise DataError(f"Yahoo Finance failed for {symbol}: {error}") from error
        return MarketData(frames, "Yahoo Finance via yfinance; unadjusted regular-session OHLCV", datetime.now(timezone.utc).isoformat(), metadata)


def session_frames(data: MarketData, session: Session, config: AgentConfig, complete_until=None):
    grid = session.grid(config.minutes)
    if complete_until is not None:
        now = pd.Timestamp(complete_until).tz_convert("UTC")
        grid = pd.DatetimeIndex([stamp for stamp in grid if session.bar_end(stamp, config.minutes) <= now])
    frames = {}
    for symbol in config.symbols:
        if symbol not in data.frames:
            raise DataError(f"No data for {symbol}")
        frame = normalize_bars(data.frames[symbol])
        missing = grid.difference(frame.index)
        if len(missing):
            raise DataError(f"{symbol}: missing {len(missing)} session bars; first missing {missing[0].isoformat()}. No prices were filled.")
        selected = frame.reindex(grid)
        frames[symbol] = clean_bars(selected) if len(grid) else selected
    return frames


class SyntheticFeed:
    """Seeded, explicitly synthetic complete sessions for offline demonstrations."""
    def __init__(self, sessions: list[Session], seed: int = 7):
        self.sessions, self.seed = sessions, seed

    def fetch(self, symbols, start, end, interval):
        rng = np.random.default_rng(self.seed)
        frames = {}
        for offset, symbol in enumerate(symbols):
            rows, index = [], []
            price = 100 + offset * 30
            for session in self.sessions:
                if not start <= session.date <= end:
                    continue
                for step, timestamp in enumerate(session.grid(int(interval[:-1]))):
                    opening = price
                    price = opening * (1 + 0.0004 * np.sin(step / 7) + rng.normal(0, 0.001))
                    rows.append([opening, max(opening, price) * 1.0004, min(opening, price) * 0.9996, price, int(rng.integers(50000, 250000))])
                    index.append(timestamp)
            frames[symbol] = pd.DataFrame(rows, index=pd.DatetimeIndex(index), columns=["Open", "High", "Low", "Close", "Volume"])
        return MarketData(frames, f"SYNTHETIC demonstration data (seed {self.seed}); not Yahoo Finance", datetime.now(timezone.utc).isoformat(), {symbol: {"currency": "USD"} for symbol in symbols})
