"""NYSE sessions, including holidays, early closes and daylight saving time."""
from dataclasses import dataclass
from datetime import datetime, timezone

import exchange_calendars as xcals
import pandas as pd


@dataclass(frozen=True)
class Session:
    date: str
    open: pd.Timestamp
    close: pd.Timestamp

    def grid(self, minutes: int) -> pd.DatetimeIndex:
        return pd.date_range(self.open, self.close, freq=f"{minutes}min", inclusive="left")

    def bar_end(self, start: pd.Timestamp, minutes: int) -> pd.Timestamp:
        return min(start + pd.Timedelta(minutes=minutes), self.close)


class MarketCalendar:
    def __init__(self):
        self.calendar = xcals.get_calendar("XNYS", start="2000-01-01", end=f"{datetime.now(timezone.utc).year + 5}-12-31")

    def sessions(self, start: str, end: str) -> list[Session]:
        if pd.Timestamp(start) > pd.Timestamp(end):
            raise ValueError("start must not be after end")
        return [Session(str(label.date()), self.calendar.session_open(label), self.calendar.session_close(label))
                for label in self.calendar.sessions_in_range(start, end)]

    def latest_completed(self, now=None) -> Session:
        now = pd.Timestamp(now or datetime.now(timezone.utc)).tz_convert("UTC")
        start = (now - pd.Timedelta(days=15)).date().isoformat()
        completed = [session for session in self.sessions(start, now.date().isoformat()) if session.close <= now]
        if not completed:
            raise ValueError("No completed session in calendar window")
        return completed[-1]

    def upcoming(self, now=None) -> Session:
        now = pd.Timestamp(now or datetime.now(timezone.utc)).tz_convert("UTC")
        return next(session for session in self.sessions(now.date().isoformat(), (now + pd.Timedelta(days=15)).date().isoformat()) if session.close > now)
