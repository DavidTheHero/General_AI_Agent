"""Lightweight semantic memory store backed by SQLite and hashed embeddings."""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

TOKEN_RE = re.compile(r"[a-zA-Z0-9']+")


def _normalize_token(token: str) -> str:
    return token.lower().strip("'")


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if not norm_a or not norm_b:
        return 0.0
    return dot / (norm_a * norm_b)


class SemanticEmbedder:
    """Simple hashed bag-of-words embedder to avoid heavyweight dependencies."""

    def __init__(self, dimensions: int = 256):
        self.dimensions = max(32, dimensions)

    def embed(self, text: str) -> List[float]:
        if not text:
            return [0.0] * self.dimensions
        vector = [0.0] * self.dimensions
        for token in TOKEN_RE.findall(text):
            normalized = _normalize_token(token)
            if not normalized:
                continue
            idx = hash(normalized) % self.dimensions
            vector[idx] += 1.0
        return vector


@dataclass
class SemanticEntry:
    entry_id: int
    session_id: str
    role: str
    content: str
    metadata: Dict[str, Any]
    embedding: List[float]
    created_at: float
    score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.entry_id,
            "session_id": self.session_id,
            "role": self.role,
            "content": self.content,
            "metadata": self.metadata,
            "score": self.score,
            "timestamp": self.created_at,
        }


class SemanticMemoryStore:
    """Stores conversation snippets with embeddings for later retrieval."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        embedder: Optional[SemanticEmbedder] = None,
    ):
        self.db_path = Path(db_path or os.environ.get("SEMANTIC_DB_PATH", "semantic_memory.db"))
        self.embedder = embedder or SemanticEmbedder()
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS semantic_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata TEXT,
                    embedding TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_semantic_session ON semantic_memory(session_id, created_at DESC)"
            )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def add_entry(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        if not content:
            return -1
        embedding = self.embedder.embed(content)
        payload = json.dumps(metadata or {})
        vector_blob = json.dumps(embedding)
        with self._lock, self._conn:
            cursor = self._conn.execute(
                """
                INSERT INTO semantic_memory (session_id, role, content, metadata, embedding, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session_id, role, content, payload, vector_blob, time.time()),
            )
            return cursor.lastrowid

    def query(
        self,
        session_id: str,
        query_text: str,
        top_k: int = 3,
        min_score: float = 0.15,
    ) -> List[Dict[str, Any]]:
        if not query_text:
            return []
        vector = self.embedder.embed(query_text)
        with self._lock:
            cursor = self._conn.execute(
                """
                SELECT id, role, content, metadata, embedding, created_at
                FROM semantic_memory
                WHERE session_id = ?
                ORDER BY created_at DESC
                LIMIT 200
                """,
                (session_id,),
            )
            candidates = cursor.fetchall()

        scored: List[SemanticEntry] = []
        for row in candidates:
            embedding = json.loads(row["embedding"])
            score = _cosine_similarity(vector, embedding)
            if score < min_score:
                continue
            metadata = json.loads(row["metadata"] or "{}")
            scored.append(
                SemanticEntry(
                    entry_id=row["id"],
                    session_id=session_id,
                    role=row["role"],
                    content=row["content"],
                    metadata=metadata,
                    embedding=embedding,
                    created_at=row["created_at"],
                    score=score,
                )
            )

        scored.sort(key=lambda item: item.score, reverse=True)
        return [entry.to_dict() for entry in scored[:top_k]]

    def delete_session(self, session_id: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "DELETE FROM semantic_memory WHERE session_id = ?",
                (session_id,),
            )

    def list_sessions(self) -> List[str]:
        with self._lock:
            cursor = self._conn.execute(
                "SELECT DISTINCT session_id FROM semantic_memory ORDER BY session_id"
            )
            rows = cursor.fetchall()
            return [row["session_id"] for row in rows]


__all__ = ["SemanticMemoryStore", "SemanticEmbedder"]
