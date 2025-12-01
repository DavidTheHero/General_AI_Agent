"""Lightweight utilities to measure component timings."""

from __future__ import annotations

import time
from collections import defaultdict
from contextlib import contextmanager
from typing import Dict, List


class TimingRecorder:
    """Collects timing samples (in milliseconds) for arbitrary steps."""

    def __init__(self):
        self._samples: Dict[str, List[float]] = defaultdict(list)

    def reset(self) -> None:
        self._samples.clear()

    @contextmanager
    def track(self, name: str):
        start = time.perf_counter()
        try:
            yield
        finally:
            duration = (time.perf_counter() - start) * 1000.0
            self._samples[name].append(duration)

    def summary(self) -> Dict[str, Dict[str, float]]:
        snapshot = {}
        for name, values in self._samples.items():
            total = sum(values)
            count = len(values)
            snapshot[name] = {
                "count": count,
                "total_ms": round(total, 2),
                "avg_ms": round(total / count, 2) if count else 0.0,
            }
        return snapshot


__all__ = ["TimingRecorder"]
