# Assistant Agent

A Node.js backend and React chat frontend powered by LangChain.js and local Ollama. The assistant routes questions to weather, finance, news, facts, arithmetic, time, holidays, and fun tools. Chat uses a bounded agent loop with tool observations and an action trace. Structured context and SQLite semantic recall support follow-up questions.

## Quick Start

Requirements: Node.js **22.13+** (24 LTS recommended), npm, and a running [Ollama](https://ollama.com/) server. Finance tools also require Python **3.11+** for the local `yfinance` MCP server.

macOS / Linux:

```bash
npm ci
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/finance/requirements.txt
.venv/bin/python -m pip install -e '.[mcp]'
cp .env.example .env
ollama pull llama3.1:8b-instruct-q4_K_M
npm run dev
```

Windows PowerShell (Node 24 and Python 3.12 were used for verification):

```powershell
node --version
py -3.12 --version
npm ci
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/finance/requirements.txt
.\.venv\Scripts\python.exe -m pip install -e '.[mcp]'
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
ollama pull llama3.1:8b-instruct-q4_K_M
npm run dev
```

Use an installed Python 3.11+ executable instead of `py -3.12` if the Windows Python launcher is unavailable. Check versions in the terminal you will use: an older `node` or `python` earlier on PATH does not satisfy the requirements. No virtual-environment activation or execution-policy change is needed. If you already have `.venv`, verify its interpreter and packages instead of recreating it. Some environments provisioned with uv lack pip; use your existing package manager or bootstrap pip with that environment's `python -m ensurepip --upgrade` before using the pip commands.

Start `npm run trading:runtime` in another terminal for the Trading desk. See [Windows foreground deployment and shutdown](deploy/README.md#windows-foreground-operation), the [initial platform verification record](docs/WINDOWS_REVIEW.md), and the [independent follow-up](docs/PEER_WINDOWS_REVIEW.md#lead-follow-up-win-02-f1-correction-and-independent-verification). Fresh Windows dependency installation in paths containing spaces and the final Windows checks passed in the follow-up. Current hosted Windows, macOS and minimum-version results and delivery status are recorded in [Windows delivery PR #9](https://github.com/DavidTheHero/General_AI_Agent/pull/9). Hosted application checks do not verify service installation.

Start Ollama separately with `ollama serve` if it is not already running. Open **http://localhost:2611**. Express runs on port 2610; Vite proxies the React frontend's API requests to it. Only the backend talks to Ollama and external tool services.

For separate development processes:

```bash
npm run dev:backend
npm run dev:frontend
```

## Python Intraday Trading Framework

The [`trading_agent/`](trading_agent/README.md) package runs autonomous Yahoo Finance intraday simulations with configurable rule or local Ollama policies. It tracks portfolio P&L, execution costs, drawdown and exposure, then generates executive reports, charts and audit ledgers automatically. Use it through the CLI or the integrated trading MCP server and React dashboard. Replay and delayed near-real-time polling follow New York market sessions, including holidays and early closes.

```bash
.venv/bin/python -m pip install -e .
.venv/bin/python -m trading_agent demo
.venv/bin/python -m trading_agent backtest --config examples/trading_sma.json
```

The CLI prints the generated `report.html` path. See the [framework guide](trading_agent/README.md) for polling, AI policies, configuration, execution assumptions and tests. This package simulates orders; it does not connect to a broker.

## Trading MCP, Runtime & Dashboard

Start the independent runtime in another terminal, alongside `npm run dev`:

```bash
npm run trading:runtime
```

Open **http://localhost:2611** → **Trading desk**. Run a synthetic demo, replay completed Yahoo sessions, or select **Watch Yahoo sessions** and **Continue across future sessions**. The dashboard refreshes every three seconds; equity, positions, recent fills and policy decisions update after completed bars. Reports and CSV/JSON/PNG exports appear automatically. Closing the page or disconnecting MCP does not cancel jobs.

Chat can also request “Run a synthetic trading demo” or “Start a continuous simulated watch of SPY and AAPL using SMA.” The MCP server retains `trading_start/status/list/stop` and adds versioned strategy discovery/validation, immutable dataset acquisition/inspection, and experiment submit/status/list/compare/cancel/audit tools. Starting returns a saved job ID immediately, followed by a dashboard link. This is a separate MCP server from the 18 read-only finance tools. Other local MCP hosts can launch `.venv/bin/python -m trading_agent.mcp_server` with this repository as their working directory; `npm run mcp:trading` also runs it over stdio.

The Trading desk's **Strategy research** view evaluates trend following, mean reversion, opening-range breakout and experimental Ollama under shared deterministic execution and risk controls. Studies preserve raw adapter responses, checksummed datasets, chronological folds, attempted configurations, cost-matched benchmarks, stressed costs and independently reconciled ledgers. A separate frozen-parent evaluation consumes the reserved final period once. See the [research workflow and limits](trading_agent/README.md#reproducible-research-workflow) and [phased design](ROADMAP.md). Reproduce the offline workflow with `.venv/bin/python -m examples.research_workflow --output artifacts/trading/my-research-verification`. Synthetic results establish software behavior; no strategy edge is currently supported.

The current research priority is **a profitable daily/multi-day edge**, using free US stock/ETF data first. A separate `trading_daily_research_start/status` workflow carries normalized total-return proxy positions overnight and has completed a real SPY/IEF/GLD study. Its positive historical returns remain **inconclusive** as evidence of an edge; strategy promotion is blocked. Read the [actual pilot results](docs/EDGE_PILOT.md), [data exploration](docs/EDGE_DATA.md) and [daily worker usage](trading_agent/README.md#reproducible-research-workflow). The intraday simulator continues to close positions daily; it is not silently reused for the new horizon.

The separately declared `trading_sector_research_start/status` study has also completed on real data. Its fixed primary earned 12.60% validation CAGR versus 11.83% SPY at 5-bps modeled costs, with uncertainty spanning zero and its excess disappearing at 20 bps. [All four configurations, corporate-action limitations and reproducible evidence](docs/SECTOR_EDGE_PILOT.md) remain `research_only`; no profitable strategy has been promoted.

Product selection is now unrestricted. A subsequent `trading_weekly_research_start/status` study broadened exposure to global equities, Treasury durations, gold and commodity futures through nine ETFs. It completed 31 reconciled attempts; the primary underperformed both declared references and failed cost stress. [Actual broader-study results](docs/GLOBAL_REVERSAL_PILOT.md), [product/data selection](docs/PRODUCT_SELECTION.md). Futures, FX and crypto remain eligible when their distinct data/accounting requirements are met. No price paths from the reserved 2023–2025 period were requested.

The execution service binds to `127.0.0.1:2612`, requires a local generated token, saves jobs in SQLite, and runs up to two worker processes. MCP is a control interface; it does not own the workers. See [deployment instructions](deploy/README.md) to keep both runtime and built dashboard running through macOS launchd. Continuous watch waits across market closures. A runtime crash marks unfinished jobs **interrupted** for review; intraday portfolio recovery is not implemented. These local services have no multi-user authorization and are intended for one user's computer.

## Production Build

```bash
npm run build
npm start
```

Express serves both the built React UI and API at **http://localhost:2610**. The server binds to localhost. Ollama must remain running separately; Node.js manages application requests, while Ollama loads and executes the model.

## Project Structure

| Path | Purpose |
| --- | --- |
| `trading_agent/`, `examples/` | Python simulation and research framework, policies, accounting, reports, and examples. |
| `trading_agent/runtime.py`, `trading_agent/mcp_server.py`, `backend/trading/` | Durable job service, trading MCP tools and Node integration. |
| `frontend/src/TradingDashboard.jsx`, `deploy/` | Live simulation dashboard, macOS service setup and Windows foreground operation. |
| `backend/server.js` | Server startup and shutdown. |
| `backend/app.js` | Express routes, input validation, and static React serving. |
| `backend/agent.js`, `backend/agent-loop.js` | Session context, model/tool loop, stop conditions, and profiling. |
| `backend/llm.js` | LangChain.js prompt chains and validated structured model outputs. |
| `backend/tools.js`, `backend/calculator.js` | JavaScript tool adapters and safe arithmetic parser. |
| `backend/finance/server.py`, `backend/finance/package_tools.py` | Python MCP server exposing 18 bounded yfinance tools. |
| `backend/finance/client.js`, `backend/finance/cli.js` | Node MCP client and standalone command-line client. |
| `backend/memory.js` | Structured context and SQLite semantic recall. |
| `backend/tests/` | Node unit and API integration tests. |
| `frontend/src/` | React chat, CSS, and component tests. |
| `frontend/vite.config.js` | Development proxy, React build, and test configuration. |

The superseded Python chat application and Flask UI have been removed; their source remains in Git history. Python is still required for the finance MCP server and trading framework. Install their dependencies from `backend/finance/requirements.txt` and `pyproject.toml` as shown above. See the [cleanup decisions](docs/REPOSITORY_CLEANUP.md) for what is kept, removed, and deferred.

## Finance Workspace

Run `npm run dev`, open the React UI at `http://localhost:2611`, and select **Finance workspace**. Choose a workflow, enter its inputs, and generate a report:

- **Company research:** profile, valuation, quarterly revenue/margins/cash flow, analyst targets, events and news.
- **Company comparison:** two to four tickers, common-date adjusted returns and financial metrics for identical fiscal quarter ends.
- **Earnings explorer:** quarterly statements, revenue changes, margins and cash-flow charts.
- **ETF overlap:** two funds, shared available holdings and weight coverage. Overlap is a lower bound because Yahoo supplies selected holdings.
- **Stock screener:** sector, positive earnings, maximum P/E and debt/equity percentage (100 means 1× equity), with filter explanations.
- **Portfolio currency:** quantities and display currency; optionally enter per-share cost basis and purchase date to separate stock and FX effects. Use split-adjusted cost basis; dividends are excluded. Holdings are not persisted.
- **Market morning brief:** selected date, US benchmark snapshot, earnings/economic calendars, news and optional watchlist. Generated on demand; scheduling and delivery are deferred.

Reports include observation dates, underlying MCP responses, source links and partial-data warnings. Missing values remain unavailable. Price snapshots are daily observations; financial statement currencies remain explicit. The reference timezone labels the requested calendar date; unknown event times are not converted.

Chat also supports workspace requests, for example “Give me a company research brief on Nvidia.” Forms provide direct, validated inputs without requiring model routing. `POST /finance/workspace` accepts a workflow request and returns the same report; for example `{"workflow":"research","symbol":"NVDA"}`. Implementation lives in `backend/finance/workspace.js`, `frontend/src/FinanceWorkspace.jsx` and `frontend/src/FinanceReport.jsx`.

## Agent Loop

Chat follows **decide → execute → observe → decide**, using local Ollama's validated structured outputs through LangChain with an explicit 16,384-token context window to accommodate tool schemas and observations. Each iteration selects a tool, asks for clarification, or finishes. MCP results and failures are fed back as observations so the model can change its lookup strategy instead of stopping after one empty search. Company briefs first call `resolve_company` with separate name and country inputs. The resolver searches the name, falls back to stock lookup and a fuller-name search when needed, and checks at most three candidate profiles against company name, country and provider symbol. It returns a resolved identity, ambiguity, no verified match or provider unavailability. Only a resolved identity enables report generation. Tool names are constrained in the model output schema at every step. Other company research, earnings and comparison reports require metadata inspection before execution; matching those identities to the request remains the model's responsibility.

The host permits at most **six tool actions per message segment**, blocks identical repeated calls and supplies one corrective observation before stopping continued repetition, rejects unknown tools, and stops cleanly on invalid planner output. Workspace and resolver actions can perform several internal MCP requests; the resolver records those attempts in the action trace. Company info is reduced to explicit identity fields for model context. Other tool responses sent to the model are limited to 2,500 characters each and marked when truncated; complete reports remain available in the UI. For a company or benchmark brief, a generated report satisfies the explicit completion condition and stops the loop without another model call. Partial results and provider availability are disclosed. Educational answers can finish without tools; current-data requests require evidence in the loop prompt.

Expand **Agent actions** under an answer to inspect executed tools and stop reasons (`metadata.agent_trace`). Usage and timing fields remain compatible with the existing API. The direct Finance workspace forms keep their deterministic calculations. Trading simulations run in the separate job service; chat retains their IDs for status follow-ups. Chat execution itself has no durable checkpoint or nested agents.

## Context-aware Conversation

Short follow-ups such as “what about that?” are rewritten into standalone requests using recent messages from the same session. Explicit inputs remain user-provided; missing essential inputs produce a targeted clarification. Original messages stay in chat/history, while `metadata.query_rewrites` records the effective requests. Rewriting falls back to the original message if its model call fails.

“How is the stock market today?” uses the on-demand US benchmark brief without requiring a ticker. “Surprise me” continues that market request, including older conversations that previously asked for a ticker. “Try again” repeats the last effective request. Other regions and historical dates go through normal routing instead of silently defaulting to today's US market.

Tool failures return an honest availability message with ways to continue; technical details remain in `metadata.tool_errors`. Rewriting cannot restore an unavailable upstream service or provide prices without evidence.

## Finance MCP Server and Client

The server now exposes **18 MCP tools** across yfinance data families: fundamentals, statements, actions, estimates, holders, funds, options, calendars, regional markets, sectors, screeners, batch/intraday history, and bounded streaming. See [the complete capability guide](backend/finance/CAPABILITIES.md) for tool names, datasets, examples, limits, and administrative exclusions. Other MCP hosts can also read `yfinance://capabilities`.

```text
React → Express/LangChain.js → Node MCP client → stdio → Python MCP server → yfinance → Yahoo Finance
```

The backend starts the finance server lazily on the first finance request. The MCP connection performs initialization, discovers tools, and calls `search_stocks`, `stock_history`, `stock_quote`, and `exchange_rate`. It stays open for reuse and closes with the backend. Calls are serialized and have a 30-second timeout; a timed-out server is closed and restarted on the next request. Advanced finance chat requests use discovered MCP schemas through the loop’s `mcp.*` actions; non-finance tools still use their existing adapters.

You can use the standalone client without Ollama or Express:

```bash
npm run mcp:finance -- list
npm run mcp:finance -- stock_quote '{"symbol":"TTWO"}'
npm run mcp:finance -- stock_history '{"symbol":"TTWO","days":7}'
npm run mcp:finance -- search_stocks '{"query":"Take-Two Interactive"}'
npm run mcp:finance -- exchange_rate '{"from_currency":"USD","to_currency":"GBP"}'
```

For another MCP host, configure a stdio server with your virtual environment's absolute Python executable as `command` and the absolute path to `backend/finance/server.py` as its sole argument. MCP messages use stdout; logs use stderr. There is no separate HTTP port or remote server to start.

After a stock quote, ask “Can you change that to GBP?” The agent converts the saved price using a yfinance FX pair such as `USDGBP=X`, showing both the stock and FX dates. Currency codes are not treated as stock symbols; conversion retains the original quote. Conversations created before this change need a fresh stock quote first.

The server returns unadjusted daily bars (up to 366 trading observations), source, currency, exchange, timezone, and dates. Quote changes are unavailable when there is no previous bar. `yfinance` is unaffiliated with Yahoo and remains subject to Yahoo availability and data-use terms; see the [official project](https://github.com/ranaroussi/yfinance). This integration is intended for personal research use.

## API & Memory

- `GET /health` returns `{ "status": "ok" }` for the application server; it does not check model readiness.
- `POST /query` accepts `{ "query": "...", "metadata": { "session_id": "abc" } }`.
- `POST /memory/search` accepts `{ "session_id": "abc", "query": "Paris", "top_k": 5 }`.
- `POST /memory/reset` accepts `{ "session_id": "abc" }` and clears that session's semantic history. Without a session ID, it returns default structured context without deleting history.
- `GET/POST /trading/jobs` lists/starts simulations; `GET /trading/jobs/:id` reads progress, `POST /trading/jobs/:id/stop` cancels, and `GET /trading/jobs/:id/artifacts/:name` serves allowed report files.

Responses retain `answer`, `responses`, `usage`, `token_usage`, `metadata`, `latency_ms`, and `timings`. Token counts are estimates. Set `metadata.response_mode` to `api` for concise answers. Send the returned structured metadata with the next query to preserve stock, weather, fact, time, and reminder context. Use a distinct session ID for each conversation.

React keeps the current conversation and metadata in browser session storage, sends a stable session ID, and clears backend memory when resetting. SQLite stores conversation snippets per session. Routing includes the last four messages so clarification replies retain context, alongside semantic matches. Existing `semantic_memory.db` entries remain readable; the JavaScript store re-embeds text with deterministic hashes for retrieval. No embedding model download is required. Concurrent requests have separate agent state.

## Configuration

Copy `.env.example` to `.env`. Backend scripts load it automatically; Vite reads it for the development proxy.

| Variable | Default | Purpose |
| --- | --- | --- |
| `PORT` | `2610` | Express API and production UI port. |
| `OLLAMA_HOST` | `http://localhost:11434` | Local Ollama server. |
| `OLLAMA_MODEL` | `llama3.1:8b-instruct-q4_K_M` | Downloaded Ollama model name. |
| `SEMANTIC_DB_PATH` | `semantic_memory.db` | SQLite conversation store. |
| `MCP_PYTHON` | Repository `.venv/Scripts/python.exe` on Windows or `.venv/bin/python` on POSIX; otherwise `python` / `python3` respectively | Override the finance/trading interpreter with an executable path only, without arguments. Paths containing spaces are supported. |
| `AGENT_API_URL` | `http://localhost:2610` | Vite API proxy target, without `/query`. |
| `TRADING_RUNTIME_PORT` | `2612` | Local execution-service port; use the same value for Node/MCP/runtime. |
| `TRADING_DATA_DIR` | Absolute repository `artifacts/trading/runtime` | Shared job database, local token, logs and report directory. |

Ollama must support structured JSON output. Stock quotes and comparisons use the local MCP server and yfinance daily price bars; quote replies identify the source and date, rather than promising real-time prices. External services require internet access and may return availability or rate-limit errors. No tool API keys are needed. Do not commit `.env`, databases, `node_modules/`, or build outputs.

## Testing & Contributing

```bash
npm test
npm run build
.venv/bin/python -m unittest discover -s trading_agent/tests -v
```

Install the finance Python requirements and `.[mcp]` package before testing, as shown in Quick Start. Tests mock models and external services, including a real MCP stdio connection to a Python server with fake Yahoo data, so they do not require Ollama or network access. They cover tool behavior, memory persistence and session isolation, stock plans and follow-ups, API validation, and React interaction. See [CONTRIBUTING.md](CONTRIBUTING.md), [AGENTS.md](AGENTS.md), and [ROADMAP.md](ROADMAP.md) for contributor guidance and planned work.
