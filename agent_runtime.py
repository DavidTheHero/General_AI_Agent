import os
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

from general_agent import AssistantAgent
from memory import default_memory
from semantic_memory import SemanticMemoryStore

SEMANTIC_STORE = SemanticMemoryStore(
    Path(os.environ.get("SEMANTIC_DB_PATH", "semantic_memory.db"))
)


@lru_cache(maxsize=1)
def get_agent() -> AssistantAgent:
    """Return a singleton AssistantAgent, creating the chat model once."""
    return AssistantAgent(semantic_store=SEMANTIC_STORE)


def run_agent_query(query: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Execute the agent with the given query and return structured data."""
    start = time.perf_counter()
    agent = get_agent()
    prediction = agent(query, metadata=metadata)
    elapsed_ms = round((time.perf_counter() - start) * 1000.0, 2)
    timings = {}
    metadata_payload = getattr(prediction, "metadata", {}) or {}
    if isinstance(metadata_payload, dict) and metadata_payload.get("timings"):
        timings = metadata_payload["timings"]
    return {
        "answer": prediction.answer,
        "responses": getattr(prediction, "responses", None),
        "usage": agent.usage_summary(),
        "token_usage": agent.token_usage(),
        "metadata": metadata_payload,
        "latency_ms": elapsed_ms,
        "timings": timings,
    }


def reset_memory_state(session_id: Optional[str] = None) -> Dict[str, Any]:
    """Clear semantic memory for the session and return a default structured map."""
    if session_id:
        SEMANTIC_STORE.delete_session(session_id)
    return {"metadata": default_memory(), "session_id": session_id}


def semantic_search(session_id: str, query: str, top_k: int = 5) -> Dict[str, Any]:
    """Return semantic matches for a given session/query."""
    matches = SEMANTIC_STORE.query(session_id, query, top_k=top_k)
    return {"matches": matches, "session_id": session_id}
