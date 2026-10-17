# Contributing

Use the [agent-assisted GitHub delivery workflow](docs/AGENT_WORKFLOW.md) for issues, isolated task branches, scoped commits, independent review, PR checks and verified merges. A local handoff or passing test report is not a merged delivery.

## Development Workflow

1. Install Node.js 22.13+ (24 LTS recommended), install Python 3.11+, run `npm ci`, create `.venv`, install `backend/finance/requirements.txt`, and copy `.env.example` to `.env`.
2. Start local Ollama and pull the configured model. Run `npm run dev` to start Express on port 2610 and React on port 2611.
3. Make focused changes in `backend/` or `frontend/src/`. The active application is JavaScript; `backend/finance/server.py` is the Python finance MCP server. Older root-level Python files remain migration references.
4. Add tests for new behavior or bug fixes. Run `npm test` and `npm run build` before submitting changes. Tests use mocked models and services.
5. Update README when setup, configuration, API fields, or behavior changes. Reference `ROADMAP.md` when proposing larger features.

## Pull Request Checklist

- Explain the problem and resulting behavior; link the relevant issue or roadmap item.
- Include test and production-build results.
- Keep API payload field names compatible with existing clients.
- Include screenshots for UI changes and timing notes for performance changes.
- Keep secrets, `.env`, generated databases, `node_modules/`, and `frontend/dist/` out of commits.

Use concise commit subjects and small, reviewable changes. Discuss major architecture changes in an issue or draft PR before implementation. No repository-wide formatter, linter, or numeric coverage threshold is configured.

## Python Simulation Development

Install the trading framework with `.venv/bin/python -m pip install -e .`. Keep its data adapters, policies, execution/accounting and reporting in the separate modules under `trading_agent/`; examples live in `examples/`. Add meaningful tests in `trading_agent/tests/` and run `.venv/bin/python -m unittest discover -s trading_agent/tests -v`. Check a full-session demo and report artifacts when changing metrics or charts. Generated reports under `artifacts/trading/` and editable-install metadata are ignored. Never introduce future-bar access, implicit price filling, mixed-currency valuation or same-bar signal fills.

The trading MCP facade and durable runtime are integrated with chat and `TradingDashboard.jsx`. Run `npm run trading:runtime` separately. Test job lifecycle, cancellation, disconnected clients, progress polling, artifact boundaries and restart interruption when editing this integration. `deploy/install_service.py` can print service definitions without installing them.
