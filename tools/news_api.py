from typing import Dict, List

import requests

REDDIT_SEARCH_ENDPOINT = "https://www.reddit.com/search.json"
USER_AGENT = "APPS-Agent/0.1 (https://example.com/contact)"


class NewsAPIError(Exception):
    """Raised when news requests fail."""


def search_news(query: str, language: str = "en", max_results: int = 5) -> List[Dict]:
    if not query:
        raise ValueError("query cannot be empty.")

    response = requests.get(
        REDDIT_SEARCH_ENDPOINT,
        params={
            "q": query,
            "sort": "new",
            "limit": max(1, min(max_results, 20)),
            "type": "link",
        },
        headers={"User-Agent": USER_AGENT},
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    posts = payload.get("data", {}).get("children", [])

    results: List[Dict] = []
    for post in posts:
        data = post.get("data", {})
        if not data:
            continue
        results.append(
            {
                "title": data.get("title"),
                "url": data.get("url"),
                "source": f"r/{data.get('subreddit')}",
                "published_at": data.get("created_utc"),
                "description": data.get("selftext"),
            }
        )
    if not results:
        raise NewsAPIError(f"No articles found for '{query}'.")

    return results
