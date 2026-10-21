# Repository Guidelines

## Project Structure & Module Organization

The active runtime is JavaScript: `backend/server.js` starts Express, `backend/app.js` defines API routes, and `backend/agent.js` orchestrates LangChain.js with local Ollama. Keep model prompts and schemas in `backend/llm.js`, adapters in `backend/tools.js`, arithmetic in `backend/calculator.js`, finance MCP server/client and package operations in `backend/finance/`, and SQLite/structured memory in `backend/memory.js`. The Python simulation framework lives in `trading_agent/` with configuration examples in `examples/`; keep policies, data ingestion, accounting, orchestration, metrics and reporting separate. React lives in `frontend/src/`; Vite configuration is in `frontend/vite.config.js`. Backend tests live in `backend/tests/`, and React tests sit beside components. The superseded Python chat application and Flask UI have been removed; use Git history for migration references. See `docs/REPOSITORY_CLEANUP.md` for retention decisions.

## Build, Test, and Development Commands

Use Node.js 22.13+ (24 LTS recommended) and Python 3.11+ for finance MCP. Run commands from the repository root:

```bash
npm ci
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/finance/requirements.txt
.venv/bin/python -m pip install -e '.[mcp]'
cp .env.example .env
ollama pull llama3.1:8b-instruct-q4_K_M
npm run dev
```

`npm run up` starts Express, React and the Trading runtime together, reusing a reachable Ollama server or starting a local one. It loads `.env`; dependency installation and model downloads remain one-time setup. Ctrl+C stops its owned services through the runtime's parent-pipe shutdown. `npm run dev` starts Express on port 2610 and React on 2611 with API hot reload; start Ollama and Trading separately in that mode. `npm test` runs backend and React tests without a live model. `npm run build` bundles React into `frontend/dist/`; `npm start` serves the API and built UI on port 2610.

## Coding Style & Naming Conventions

Use ES modules, four-space indentation, `camelCase` JavaScript functions and variables, and `PascalCase` React components. Preserve `snake_case` fields in API payloads for compatibility. No formatter or linter is configured. Keep changes focused; avoid unrelated refactors. State uncertain assumptions before implementation and discuss major architecture changes through an issue or draft PR.

## Testing Guidelines

Use Node's `node:test` framework in `backend/tests/*.test.js` and Vitest with Testing Library in `frontend/src/*.test.jsx`. Mock model calls and HTTP responses; use SQLite `:memory:` for isolated tests. Add regression tests for fixes and tests for new agent behavior. No numeric coverage threshold is defined. Run `npm test` and `npm run build` before submitting changes.

## Commit & Pull Request Guidelines

Follow `docs/AGENT_WORKFLOW.md`: start from a bounded GitHub issue, use an isolated task worktree and `<type>/<issue>-<name>` branch, stage only owned files, and open a linked draft PR. Verify the exact local model/provider before each handoff; review returned diffs and run checks independently. Record lead review against the final head SHA. Merge only that reviewed revision after applicable checks and verify the merged result. Keep `Communication.md` as optional local coordination; the issue/PR records delivery. Preserve the original dirty checkout and never commit secrets or generated artifacts.

History uses brief subjects such as `re-organising` and `v1.0`; no formal commit convention is established. Write concise subjects describing the change and keep commits reviewable. PRs should explain behavior changes, report validation, and reference an issue or relevant `ROADMAP.md` item. Update documentation when behavior changes; include timing notes or screenshots for performance work.

## Security & Configuration

Configure `OLLAMA_HOST`, `OLLAMA_MODEL`, `PORT`, and `SEMANTIC_DB_PATH` through `.env`. `AGENT_API_URL` sets the Vite development proxy target. Keep secrets, `.env`, `node_modules/`, build outputs, and generated databases out of commits.

## Python Trading Framework

Install with `.venv/bin/python -m pip install -e .`; run `.venv/bin/python -m trading_agent demo` for an offline end-to-end check. Tests use `unittest` under `trading_agent/tests/`: `.venv/bin/python -m unittest discover -s trading_agent/tests -v`. Preserve completed-bar-only policy inputs, next-open target execution, explicit currency/timezone units and auditable costs. Reports must distinguish synthetic data, unavailable observations and incomplete sessions. Generated simulation artifacts belong under ignored `artifacts/trading/`.

Trading MCP tools live in `trading_agent/mcp_server.py`; `runtime.py` independently owns durable jobs and workers. Run `npm run trading:runtime` for the Trading desk. Keep MCP calls short, progress snapshots atomic, and interrupted portfolios explicit; never silently replay them. See `deploy/README.md` for macOS services.
