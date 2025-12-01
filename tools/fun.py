from typing import Dict, Optional

import requests

BORED_ENDPOINT = "https://www.boredapi.com/api/activity"
JOKE_ENDPOINT = "https://v2.jokeapi.dev/joke/Any"


class FunToolError(Exception):
    """Raised when fun utilities fail."""


def get_random_activity() -> Dict[str, str]:
    try:
        response = requests.get(BORED_ENDPOINT, timeout=10)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise FunToolError(f"Activity service unavailable: {exc}") from exc
    data = response.json()
    if "activity" not in data:
        raise FunToolError("Failed to fetch an activity.")
    return {
        "activity": data.get("activity"),
        "type": data.get("type"),
        "participants": data.get("participants"),
        "link": data.get("link"),
    }


def _request_joke(params: dict) -> dict:
    response = requests.get(JOKE_ENDPOINT, params=params, timeout=10)
    response.raise_for_status()
    data = response.json()
    if data.get("error"):
        raise FunToolError(data.get("message") or "Joke lookup failed.")
    return data


def get_random_joke(topic: Optional[str] = None) -> Dict[str, str]:
    params = {}
    attempts = []
    if topic:
        params["contains"] = topic
        attempts.append(dict(params))
    attempts.append({})

    last_error: Optional[Exception] = None

    for opts in attempts:
        try:
            data = _request_joke(opts)
            break
        except FunToolError as exc:
            last_error = exc
        except requests.RequestException as exc:
            last_error = FunToolError(f"Joke service unavailable: {exc}")
    else:
        raise last_error or FunToolError("Failed to fetch a joke.")

    if data.get("type") == "single":
        joke = data.get("joke")
    else:
        joke = f"{data.get('setup')}\n{data.get('delivery')}"

    return {"category": data.get("category"), "joke": joke}
