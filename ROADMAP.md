## Roadmap

### 1. Current State
- **Agent core**: `general_agent.py` uses DSPy to route queries to tools (weather, news, facts, finance, etc.) and provides follow-up handling for stock comparisons.
- **Tools**: Located under `tools/` and rely on public APIs (Open-Meteo, DuckDuckGo, Stooq, CoinGecko, etc.).
- **Backends**: 
  - `fastapi_app.py` exposes `/query` (POST) and `/health`.
  - `flask_app.py` provides a chat UI that forwards requests to FastAPI, maintains session metadata, and offers a Reset button.
- **Memory**: Structured slots + semantic recall. `memory.AgentMemory` tracks stock/weather/fact/time data; `semantic_memory.py` stores embeddings in SQLite per session.
- **Observability**: Each `/query` returns `latency_ms` + per-component timings; Flask UI shows a modern chat surface with timing chips and metadata toggles.
- **Tests**: `test.py` covers finance helpers, memory utilities, and semantic store basics.

### 2. Upcoming Enhancements
1. **Semantic Memory Upgrades**
   - Pluggable embedding backends (local hashed encoder vs. OpenAI, Cohere, Instructor, etc.) with config-driven selection.
   - Administrative APIs/UI toggles to inspect/delete specific semantic entries, export conversation history, and show retrieved snippets inline.
   - Background cleanup jobs (age-based pruning, session archiving) so SQLite/pgvector stores stay lean.

2. **Persistent Storage**
   - Replace Flask session storage with Redis or another external store for structured metadata; move semantic embeddings to pgvector/SQLite per user.
   - Add TTL/retention policies per context block (weather < 24h, facts < 30d, etc.).

3. **Expanded Tests**
   - Network-mocked tests for each tool + DSPy follow-up classifier.
   - Integration suite using FastAPI `TestClient` to simulate `/query` with structured + semantic metadata.
   - Front-end smoke tests (Playwright or Cypress) for the Flask UI.

4. **Chat UI Enhancements**
   - Streaming responses + typing indicators.
   - Toggle panels showing structured metadata, retrieved semantic snippets, and timing breakdowns per turn.
   - Mobile-friendly layout, theming, and keyboard shortcuts (Enter/Shift+Enter already live).

5. **Deployment Considerations**
   - Dockerize FastAPI + Flask (docker-compose, env templates).
   - Optional worker processes for blocking tool calls (Celery/RQ).
   - Document rate limits + fallback strategies in README.

### 3. Long-Term Ideas
- **Multi-user auth / session routing** with per-user memory stores and quotas.
- **Vector memory** backed by a managed vector DB (Pinecone, Weaviate) for richer semantic recall + RAG.
- **Tool orchestration / planning** via DSPy chains or a lightweight planner to coordinate multi-step tool usage.
- **LLM observability** dashboards: aggregate timings, errors, token usage across sessions for ops visibility.
