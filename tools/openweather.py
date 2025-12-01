import os
from typing import Dict, List

import requests

GEOCODE_ENDPOINT = "https://api.openweathermap.org/geo/1.0/direct"
CURRENT_WEATHER_ENDPOINT = "https://api.openweathermap.org/data/2.5/weather"
FORECAST_ENDPOINT = "https://api.openweathermap.org/data/2.5/forecast"


class OpenWeatherError(Exception):
    """Raised when OpenWeatherMap requests fail."""


def _require_api_key() -> str:
    api_key = os.environ.get("OPENWEATHER_API_KEY")
    if not api_key:
        raise OpenWeatherError("OPENWEATHER_API_KEY environment variable is required.")
    return api_key


def _geocode(location: str, api_key: str) -> Dict:
    response = requests.get(
        GEOCODE_ENDPOINT,
        params={"q": location, "limit": 1, "appid": api_key},
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()
    if not data:
        raise OpenWeatherError(f"Unable to find coordinates for '{location}'.")
    return data[0]


def _request_weather(
    endpoint: str, params: Dict[str, str | float | int]
) -> Dict:
    response = requests.get(endpoint, params=params, timeout=10)
    response.raise_for_status()
    data = response.json()
    if data.get("cod") not in (200, "200"):
        raise OpenWeatherError(str(data))
    return data


def get_weather_and_forecast(location: str, units: str = "metric") -> Dict:
    """Return current weather plus a compact forecast using OpenWeatherMap."""
    if not location:
        raise ValueError("location cannot be empty.")

    api_key = _require_api_key()
    geo = _geocode(location, api_key)
    lat = geo["lat"]
    lon = geo["lon"]

    current = _request_weather(
        CURRENT_WEATHER_ENDPOINT,
        {"lat": lat, "lon": lon, "units": units, "appid": api_key},
    )

    forecast_raw = _request_weather(
        FORECAST_ENDPOINT,
        {"lat": lat, "lon": lon, "units": units, "appid": api_key, "cnt": 12},
    )

    forecast: List[Dict] = []
    for entry in forecast_raw.get("list", []):
        forecast.append(
            {
                "time": entry.get("dt_txt"),
                "temperature": entry.get("main", {}).get("temp"),
                "feels_like": entry.get("main", {}).get("feels_like"),
                "weather": entry.get("weather", [{}])[0].get("description"),
                "wind_speed": entry.get("wind", {}).get("speed"),
            }
        )

    return {
        "location": {
            "name": geo.get("name"),
            "country": geo.get("country"),
            "state": geo.get("state"),
            "latitude": lat,
            "longitude": lon,
        },
        "current": {
            "temperature": current.get("main", {}).get("temp"),
            "feels_like": current.get("main", {}).get("feels_like"),
            "humidity": current.get("main", {}).get("humidity"),
            "description": current.get("weather", [{}])[0].get("description"),
            "wind_speed": current.get("wind", {}).get("speed"),
        },
        "forecast": forecast,
        "units": units,
        "source": "OpenWeatherMap",
    }
