import datetime as dt
from typing import Dict, List

import requests

WIKIPEDIA_API = "https://en.wikipedia.org/api/rest_v1/page/summary/{topic}"
HN_SEARCH_API = "https://hn.algolia.com/api/v1/search"
DEFAULT_HEADERS = {
    "User-Agent": "APPS-Agent/0.1 (https://example.com/contact)",
    "Accept": "application/json",
}


class InfoToolError(Exception):
    """Custom exception for info tool failures."""


def _request_json(url: str, params: Dict[str, str] | None = None) -> Dict:
    """Perform a GET request and return JSON, raising for HTTP errors."""
    try:
        response = requests.get(url, params=params, headers=DEFAULT_HEADERS, timeout=10)
        response.raise_for_status()
    except requests.HTTPError as exc:
        raise InfoToolError(f"Request to '{url}' failed: {exc}") from exc
    return response.json()


def get_topic_summary(topic: str) -> Dict[str, str]:
    """Return a concise summary of a topic from Wikipedia."""
    if not topic:
        raise ValueError("topic cannot be empty.")

    endpoint = WIKIPEDIA_API.format(topic=topic.strip().replace(" ", "_"))
    data = _request_json(endpoint)

    if data.get("type") == "disambiguation":
        raise InfoToolError(
            f"Topic '{topic}' is ambiguous. Try being more specific."
        )

    if not data.get("extract"):
        raise InfoToolError(f"No summary available for '{topic}'.")

    return {
        "title": data.get("title", topic.title()),
        "extract": data["extract"],
        "description": data.get("description", ""),
        "url": data.get("content_urls", {})
        .get("desktop", {})
        .get("page", f"https://en.wikipedia.org/wiki/{topic}"),
    }


def search_tech_news(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    """
    Search the Hacker News Algolia API for recent articles or discussions.

    Args:
        query: Search keywords (e.g., company, technology, topic).
        max_results: Maximum number of entries to return (default: 5).
    """
    if not query:
        raise ValueError("query cannot be empty.")

    params = {
        "query": query,
        "tags": "story",
        "hitsPerPage": str(max(1, min(max_results, 10))),
        "restrictSearchableAttributes": "title",
    }
    payload = _request_json(HN_SEARCH_API, params=params)
    hits = payload.get("hits", [])

    results: List[Dict[str, str]] = []
    for hit in hits:
        created_at = hit.get("created_at")
        created = (
            dt.datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            if created_at
            else None
        )
        results.append(
            {
                "title": hit.get("title") or hit.get("story_title") or "Untitled",
                "url": hit.get("url") or hit.get("story_url") or "",
                "author": hit.get("author", ""),
                "points": hit.get("points", 0),
                "created_at": created.isoformat() if created else created_at,
            }
        )

    if not results:
        raise InfoToolError(f"No results found for query '{query}'.")

    return results
