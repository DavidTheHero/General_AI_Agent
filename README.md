# Assistant Agent

An extensible DSPy-powered assistant that routes user queries to weather, finance, news, facts, and fun tools while keeping a hybrid structured + semantic memory of each conversation. A FastAPI backend runs the model, and a Flask UI provides a modern chat experience. Recent updates add a visible plan→act→reflect loop (starting with stock comparisons) so the agent feels less like a thin wrapper and more like an actual autonomous workflow.

---

## Quick Start

```bash
git clone <repo-url>
cd APPS

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Start the FastAPI API (default port 2610)
uvicorn fastapi_app:app --host 0.0.0.0 --port 2610 --reload

# Start the Flask UI (in a new shell)
export AGENT_API_URL=http://localhost:2610/query
python flask_app.py
```

Visit `http://localhost:2611` to chat. The UI communicates with FastAPI, which keeps the DSPy model and memory in-process.

---

## Project Structure

| Path | Purpose |
| --- | --- |
| `fastapi_app.py` | FastAPI API exposing `/query`, `/health`, `/memory/*`. |
| `flask_app.py`, `templates/`, `static/` | Chat UI that streams messages, shows timing chips, and stores session metadata. |
| `general_agent.py` | DSPy agent orchestrator (router + planner registry + profiling). |
| `agent/signatures.py` | DSPy routing/answer signatures + tool catalog. |
| `agent/utils.py` | Shared helpers (query splitting, ticker extraction, etc.). |
| `agent/planners/` | Plan/act/reflect modules (e.g., stock comparison planner). |
| `memory.py` | Structured memory helper (stock/weather/fact/time contexts). |
| `semantic_memory.py` | SQLite-backed semantic store for prior conversation snippets. |
| `tools/` | Individual tool adapters (finance, weather, jokes, etc.). |
| `profiling.py` | Lightweight timing recorder used across the agent. |
| `test.py` | Unit tests (finance, memory helpers, semantic store). |
| `README.md`, `ROADMAP.md`, `CONTRIBUTING.md` | Docs and roadmap. |

`semantic_memory.db` is generated locally (and ignored via `.gitignore`). Set `SEMANTIC_DB_PATH` to relocate it.

---

## Memory & Context

The assistant blends deterministic metadata with semantic recall:

- **Structured map** – `memory.AgentMemory` tracks tool-specific state. Every `/query` accepts a `metadata` payload and returns the updated map so clients can persist per-session context.
- **Semantic backlog** – `SemanticMemoryStore` embeds each turn into SQLite (hashed bag-of-words) keyed by `session_id`. Similar snippets are prepended to DSPy router prompts so ambiguous follow-ups (“compare them again”) have context, and the retrieved snippets + planner trace are included in metadata for debugging.
- **API helpers** – FastAPI exposes:
  - `POST /memory/reset` with `{ "session_id": "abc" }` to clear structured + semantic state for a session.
  - `POST /memory/search` with `{ "session_id": "abc", "query": "travel plans" }` to inspect recalled snippets without running the agent.
- **Plan/act/reflect** – Planners (starting with `StockComparisonPlanner`) detect complex queries, build execution steps, call the relevant tools, then reflect (e.g., store reminders about the winning stock). Each response returns a `plan_trace` so you can inspect the agent cycle, and more planners can be added under `agent/planners/`.
- **Response style** – Add `"response_mode": "api"` to metadata for concise tool-like replies; default `"natural"` returns conversational prose.

Schema overview:

```jsonc
{
  "stock_context": {
    "last_comparison": {"entries": [], "days": 0, "timestamp": "", "symbols": []},
    "comparison_history": [],
    "recent_symbols": []
  },
  "weather_context": {"last_location": {}, "last_conditions": {}, "last_updated": ""},
  "fact_context": {"recent_facts": []},
  "time_context": {
    "last_timezone_request": null,
    "last_time_result": null,
    "last_conversion": null
  },
  "user_profile": {}
}
```

Supply a stable `session_id` when POSTing to `/query` so the same user pulls their context.

---

## Observability & Performance

Profiling is built-in:

- Every `/query` response includes `latency_ms` **and** a `timings` map (also mirrored under `metadata.timings`). Each entry contains `count`, `total_ms`, and `avg_ms` for the component (e.g., `lm_router`, `tool_stock_quote`, `semantic_lookup`).
- The Flask UI shows each request’s latency chip plus a “Timings” disclosure to inspect per-step averages.
- `tool_usage` and `token_usage` remain alongside responses for additional visibility.

Use these metrics to spot slow APIs or redundant LM calls before opening PRs.

---

## Testing

```bash
python3 -m unittest test
```

Tests currently cover finance helpers + memory utilities. Please add tests for new tools or agent behaviors when contributing.

---

## Environment Variables

| Variable | Description | Default |
| --- | --- | --- |
| `AGENT_API_URL` | Flask UI → FastAPI endpoint. | `http://localhost:2610/query` |
| `SEMANTIC_DB_PATH` | Path for the SQLite semantic store. | `semantic_memory.db` |
| `DSPY_MODEL` | DSPy model identifier (e.g., `ollama/llama3.1:8b`). | `ollama/llama3.1:8b-instruct-q4_K_M` |
| `FLASK_SECRET_KEY` | Session secret for UI. | `dev-secret` (override in prod) |

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the workflow, PR checklist, and environment setup. The short version:

1. Install deps via `pip install -r requirements.txt`.
2. Keep tests green (`python3 -m unittest test`).
3. Reference [ROADMAP.md](ROADMAP.md) when implementing new features.
4. Don’t commit generated files (`semantic_memory.db`, `__pycache__`, etc.).

---

## Roadmap

Upcoming enhancements (persistent stores, improved embeddings, UI observability, deployment) live in [ROADMAP.md](ROADMAP.md). Open an issue or draft PR to discuss any large changes before implementation.
# General_AI_Agent
