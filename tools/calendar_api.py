from typing import Dict, List

import requests

NAGER_ENDPOINT = "https://date.nager.at/api/v3/PublicHolidays"


class CalendarAPIError(Exception):
    """Raised when holiday requests fail."""


def get_holidays(country: str, year: int, month: int | None = None) -> List[Dict]:
    if not country:
        raise ValueError("country cannot be empty.")

    response = requests.get(f"{NAGER_ENDPOINT}/{year}/{country}", timeout=10)
    response.raise_for_status()
    data = response.json()

    holidays = data or []
    if month:
        holidays = [
            holiday
            for holiday in holidays
            if _extract_month(holiday.get("date")) == month
        ]
    if not holidays:
        raise CalendarAPIError("No holidays found for the specified query.")

    normalized = []
    for holiday in holidays:
        normalized.append(
            {
                "name": holiday.get("localName"),
                "description": holiday.get("name"),
                "date": holiday.get("date"),
                "type": holiday.get("types"),
            }
        )
    return normalized


def _extract_month(date_str: str | None) -> int:
    if not date_str or len(date_str) < 7:
        return 0
    try:
        return int(date_str.split("-")[1])
    except (ValueError, IndexError):
        return 0
