from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class TimeToolError(Exception):
    """Raised when time utilities encounter invalid inputs."""


def _get_zone(timezone: str | None) -> ZoneInfo:
    tz = (timezone or "UTC").strip() or "UTC"
    try:
        return ZoneInfo(tz)
    except ZoneInfoNotFoundError as exc:
        raise TimeToolError(f"Unknown timezone '{timezone}'.") from exc


def current_time(timezone: str | None = None) -> dict:
    """Return the current time in ISO format plus human-friendly display."""
    zone = _get_zone(timezone)
    now = dt.datetime.now(zone)
    return {
        "timezone": zone.key,
        "iso": now.isoformat(),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "weekday": now.strftime("%A"),
    }


def convert_time(
    iso_timestamp: str,
    from_timezone: str | None,
    to_timezone: str | None,
) -> dict:
    """Convert an ISO timestamp from one timezone to another."""
    if not iso_timestamp:
        raise TimeToolError("iso_timestamp cannot be empty.")

    try:
        naive_dt = dt.datetime.fromisoformat(iso_timestamp)
    except ValueError as exc:
        raise TimeToolError(f"Invalid ISO timestamp: {iso_timestamp}") from exc

    source_zone = _get_zone(from_timezone)
    target_zone = _get_zone(to_timezone or "UTC")

    if naive_dt.tzinfo is None:
        aware_dt = naive_dt.replace(tzinfo=source_zone)
    else:
        aware_dt = naive_dt.astimezone(source_zone)

    converted = aware_dt.astimezone(target_zone)
    return {
        "source_timezone": source_zone.key,
        "target_timezone": target_zone.key,
        "source_time": aware_dt.isoformat(),
        "converted_time": converted.isoformat(),
        "converted_display": converted.strftime("%Y-%m-%d %H:%M:%S %Z"),
    }
