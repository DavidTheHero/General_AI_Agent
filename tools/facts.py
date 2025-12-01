import re
from html import unescape
from typing import Dict, List, Optional
from urllib.parse import parse_qs, unquote, urlparse

import requests

DUCKDUCKGO_ENDPOINT = "https://api.duckduckgo.com"
DUCKDUCKGO_HTML_ENDPOINT = "https://duckduckgo.com/html/"
USER_AGENT = "APPS-Agent/0.1 (https://example.com/contact)"
HTML_TAG_RE = re.compile(r"<[^>]+>")
TOKEN_RE = re.compile(r"[a-zA-Z]{2,}")
STOPWORDS = {
    "what",
    "when",
    "who",
    "whom",
    "that",
    "this",
    "with",
    "your",
    "from",
    "have",
    "been",
    "will",
    "into",
    "about",
    "there",
    "their",
    "where",
    "which",
    "would",
    "could",
    "should",
    "does",
    "doesn",
    "are",
    "can",
    "for",
    "some",
    "only",
    "than",
    "then",
    "were",
    "much",
}


class FactLookupError(Exception):
    """Raised when fact lookup fails."""


def extract_keywords(topic: str) -> List[str]:
    seen = set()
    keywords: List[str] = []
    for token in TOKEN_RE.findall(topic.lower()):
        token = token.strip("'")
        if token in STOPWORDS:
            continue
        if token in seen:
            continue
        seen.add(token)
        keywords.append(token)
        if len(keywords) >= 4:
            break
    return keywords


def _duckduckgo_answer(topic: str) -> Optional[Dict[str, str]]:
    response = requests.get(
        DUCKDUCKGO_ENDPOINT,
        params={
            "q": topic,
            "format": "json",
            "no_html": 1,
            "skip_disambig": 1,
        },
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()

    abstract = data.get("AbstractText") or data.get("Abstract")
    if not abstract:
        return None

    return {
        "topic": topic,
        "answer": abstract,
        "source": data.get("AbstractSource") or "DuckDuckGo",
        "url": data.get("AbstractURL"),
    }


def _duckduckgo_search(topic: str) -> Optional[Dict[str, str]]:
    keywords = extract_keywords(topic)
    response = requests.get(
        DUCKDUCKGO_HTML_ENDPOINT,
        params={"q": topic},
        headers={"User-Agent": USER_AGENT},
        timeout=10,
    )
    response.raise_for_status()
    html = response.text

    pattern = re.compile(
        r'class="result__a"[^>]*href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>.*?class="result__snippet"[^>]*>(?P<snippet>.*?)</a>',
        re.S,
    )

    def clean(text: str) -> str:
        return unescape(HTML_TAG_RE.sub("", text)).strip()

    best = None
    best_score = -1
    for match in pattern.finditer(html):
        title = clean(match.group("title"))
        snippet = clean(match.group("snippet"))
        snippet_lower = snippet.lower()
        score = 0
        for kw in keywords:
            if kw in snippet_lower or kw in title.lower():
                score += 1

        if score == 0:
            continue

        raw_url = unescape(match.group("url"))
        if raw_url.startswith("//"):
            raw_url = f"https:{raw_url}"

        parsed = urlparse(raw_url)
        if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
            params = parse_qs(parsed.query)
            if "uddg" in params:
                raw_url = unquote(params["uddg"][0])

        candidate = {
            "topic": topic,
            "answer": snippet,
            "source": title,
            "url": raw_url,
        }

        if score > best_score or best is None:
            best = candidate
            best_score = score

    return best


def get_instant_answer(topic: str) -> Dict[str, str]:
    if not topic:
        raise ValueError("topic cannot be empty.")

    ddg_result = _duckduckgo_answer(topic)
    if ddg_result:
        return ddg_result

    search_result = _duckduckgo_search(topic)
    if search_result:
        return search_result

    raise FactLookupError(f"No instant answer available for '{topic}'.")
