import requests

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"


def _query_geocode(name: str) -> list[dict]:
    response = requests.get(
        GEOCODE_URL,
        params={
            "name": name,
            "count": 5,
            "language": "en",
            "format": "json",
        },
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()
    results = data.get("results") or []
    return results


def _geocode_location(location: str) -> dict:
    """Resolve a location string to coordinates using Open-Meteo's geocoder."""
    if not location:
        raise ValueError("location cannot be empty.")

    candidates = []
    base = location.strip()
    if base:
        candidates.append(base)

    if "," in base:
        parts = [p.strip() for p in base.split(",") if p.strip()]
        candidates.extend(parts)
        candidates.append(" ".join(parts))

    seen = set()
    all_results: list[dict] = []
    for candidate in candidates:
        key = candidate.lower()
        if not candidate or key in seen:
            continue
        seen.add(key)

        results = _query_geocode(candidate)
        if results:
            all_results.extend(results)

    if not all_results:
        raise ValueError(f"Unable to find coordinates for '{location}'.")

    query_lower = location.lower()

    def score(result: dict) -> float:
        value = 0.0
        fields = [
            (result.get("name"), 3.0),
            (result.get("country"), 2.0),
            (result.get("admin1"), 1.5),
            (result.get("admin2"), 1.0),
        ]

        for field, weight in fields:
            if field:
                field_lower = field.lower()
                if field_lower in query_lower:
                    value += weight

        population = result.get("population") or 0
        value += min(population / 1_000_000, 1.0)
        return value

    best = max(all_results, key=score)
    return best

    raise ValueError(f"Unable to find coordinates for '{location}'.")


def get_current_weather(location: str) -> dict:
    """Return the current weather for the requested city."""
    if not location:
        raise ValueError("location cannot be empty.")

    coordinates = _geocode_location(location)
    response = requests.get(
        WEATHER_URL,
        params={
            "latitude": coordinates["latitude"],
            "longitude": coordinates["longitude"],
            "current_weather": True,
            "timezone": coordinates.get("timezone", "auto"),
        },
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json().get("current_weather")

    if not payload:
        raise RuntimeError("Weather API did not return current conditions.")

    return {
        "location": {
            "name": coordinates.get("name"),
            "country": coordinates.get("country"),
            "latitude": coordinates.get("latitude"),
            "longitude": coordinates.get("longitude"),
        },
        "weather": {
            "temperature_c": payload.get("temperature"),
            "windspeed_kmh": payload.get("windspeed"),
            "winddirection": payload.get("winddirection"),
            "time": payload.get("time"),
            "weathercode": payload.get("weathercode"),
        },
        "source": "Open-Meteo",
    }
