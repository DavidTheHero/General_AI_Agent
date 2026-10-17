# Repository cleanup decisions — 17 October 2026

The supported application is Express + React + LangChain.js with local Ollama. Python remains required for finance MCP and the simulation/research framework. This cleanup removes a superseded application, without changing the active application or its dependency versions.

## Keep

| Paths | Reason |
| --- | --- |
| `backend/`, `frontend/` | Active server, agent/tool loop, finance integration, UI and tests, reached by the npm scripts. |
| `trading_agent/`, `examples/` | Active Python simulations, durable workers, research protocols and executable examples. |
| `deploy/` | Existing macOS service installation and macOS/Linux/Windows operating instructions. |
| `package.json`, `package-lock.json` | JavaScript dependency declarations and reproducible installation. |
| `pyproject.toml`, `trading_agent/requirements.txt`, `backend/finance/requirements.txt` | Active Python package and dependency sources; finance and trading are separate installation targets. |
| `.github/`, `scripts/`, contributor guides | Issue/PR delivery rules and their validation, plus application CI. |
| Research documents under `docs/` | Frozen protocols, source limitations and actual study results, including inconclusive/failed hypotheses. These are evidence, not disposable backlog. |

## Remove

Reference searches across active source, tests, scripts, package configuration and CI found no consumers of the legacy Python chat modules. The npm scripts start the JavaScript app, and setuptools packages only `trading_agent*`.

| Removed paths | Reason |
| --- | --- |
| `agent/`, `general_agent.py`, `agent_runtime.py` | Superseded chat orchestration; active implementation is in `backend/`. |
| `memory.py`, `semantic_memory.py`, `profiling.py` | Helpers used only by that old agent; active equivalents are in JavaScript. Existing local SQLite data is retained. |
| `tools/` | Old Python chat adapters, including an unused OpenWeather adapter and empty note. Active tool adapters live under `backend/`. |
| `fastapi_app.py`, `flask_app.py`, `templates/`, `static/` | Replaced API/UI entry points and assets. Express and React own those roles. |
| `test.py` | Tests for the removed Python chat stack. Keep the active backend, React, trading and PR-policy tests. |
| Root `requirements.txt` | Dependencies for the removed Flask/FastAPI/Python-LangChain chat stack. Use the active dependency sources above. |

The removed source is recoverable from Git revision `e7932d2` (before this cleanup), for example `git show e7932d2:general_agent.py`. It does not need another archive copy in the working tree.

## Update and defer

- README, AGENTS and CONTRIBUTING point to the supported runtime and its Python installs. The roadmap distinguishes delivered finance capabilities from optional ideas, preserving dated research/design records.
- Keep the injected-chain compatibility path in `backend/agent.js`: active regression tests still exercise it. Removing it would require a separate behavior change.
- Keep local `archive/`, `artifacts/trading/`, databases, `.env`, `.venv/`, `node_modules/` and `frontend/dist/`. These ignored paths may contain provenance, local state or required installations. Disk pruning needs a separate retention decision; this cleanup removes tracked obsolete source only.
- Dependency upgrades, application refactors and research reruns are outside this cleanup. No historical price reservation is consumed.
