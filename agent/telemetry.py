"""Telemetry helpers for tracking tool and token usage."""

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class ToolEvent:
    tool: str
    query: str
    details: str = ""


class ToolUsageMonitor:
    """Collects structured telemetry for tool invocations."""

    def __init__(self):
        self.reset()

    def log(self, tool: str, query: str, details: str = "") -> None:
        event = ToolEvent(tool=tool, query=query, details=details)
        self.history.append(event)
        self.counts[tool] = self.counts.get(tool, 0) + 1

    def summary(self) -> Dict[str, int]:
        return dict(self.counts)

    def reset(self) -> None:
        self.history: List[ToolEvent] = []
        self.counts: Dict[str, int] = {}


def estimate_tokens(text: Optional[str]) -> int:
    """Rough heuristic to estimate tokens from text length."""
    if not text:
        return 0
    # Approximate 1 token per 4 characters (common heuristic for English text).
    return max(1, len(text) // 4)


@dataclass
class TokenUsageEntry:
    call_type: str
    prompt_tokens: int
    completion_tokens: int


class TokenUsageTracker:
    """Tracks approximate token usage for each LM call."""

    def __init__(self):
        self.reset()

    def log(self, call_type: str, prompt: Optional[str], completion: Optional[str]) -> None:
        entry = TokenUsageEntry(
            call_type=call_type,
            prompt_tokens=estimate_tokens(prompt),
            completion_tokens=estimate_tokens(completion),
        )
        self.entries.append(entry)

    def summary(self) -> Dict[str, int]:
        total_prompt = sum(entry.prompt_tokens for entry in self.entries)
        total_completion = sum(entry.completion_tokens for entry in self.entries)
        return {
            "calls": len(self.entries),
            "prompt_tokens": total_prompt,
            "completion_tokens": total_completion,
            "total_tokens": total_prompt + total_completion,
        }

    def last_entries(self, n: int = 5) -> List[TokenUsageEntry]:
        return self.entries[-n:]

    def reset(self) -> None:
        self.entries: List[TokenUsageEntry] = []
