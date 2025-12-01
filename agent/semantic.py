"""Utilities for working with semantic memory."""

import datetime as dt
from contextlib import nullcontext
from typing import Any, Callable, Dict, Iterable, List, Optional

ProfileStep = Callable[[str], Any]


def retrieve_semantic_context(
    semantic_store,
    session_id: str,
    query: str,
    top_k: int = 3,
) -> List[Dict[str, Any]]:
    if not semantic_store:
        return []
    return semantic_store.query(session_id, query, top_k=top_k)


def augment_query_with_context(query: str, matches: Iterable[Dict[str, Any]]) -> str:
    matches = list(matches or [])
    if not matches:
        return query
    snippets = []
    for item in matches:
        timestamp = item.get("timestamp")
        if timestamp:
            try:
                stamp = dt.datetime.fromtimestamp(timestamp).isoformat()
            except (ValueError, OSError):
                stamp = "previous"
        else:
            stamp = "previous"
        snippets.append(
            f"{item.get('role', 'assistant')} ({stamp}): {item.get('content', '')}"
        )
    context_block = "\n".join(snippets[:3])
    return f"{query}\n\nRelevant prior messages:\n{context_block}"


def record_semantic_event(
    semantic_store,
    session_id: str,
    role: str,
    content: str,
    profile_step: Optional[ProfileStep] = None,
) -> None:
    if not semantic_store:
        return
    text = (content or "").strip()
    if not text:
        return
    session = session_id or "default"
    step = profile_step("semantic_store_write") if profile_step else nullcontext()
    with step:
        semantic_store.add_entry(session, role, text)
