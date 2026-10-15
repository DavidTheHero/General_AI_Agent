# Roadmap

## Python Intraday Simulation Framework

The `trading_agent/` package implements calendar-aware historical replay and delayed near-real-time polling, modular SMA/momentum/buy-and-hold/Ollama policies, long-only whole-share accounting, next-bar execution, cost models, host risk controls and automatic daily/aggregate executive reports with analytical PNG charts and audit ledgers. See [the guide](trading_agent/README.md).

NY sessions follow 09:30–16:00 exchange-local time, holidays and early closes. No missing prices are interpolated; non-USD data and split-containing downloads fail explicitly. Polling is event-time replay with configurable source lag, not live broker execution. Real trading, broker routing, order-book liquidity, FX portfolios and durable restart/resume remain outside this simulation framework.

## Trading MCP Runtime and Dashboard

Implemented: `trading_agent/runtime.py` owns a persistent SQLite job registry and independent simulation workers; `mcp_server.py` exposes start/status/list/stop tools. The Node chat loop can invoke them and retain a job ID. React's Trading desk starts demos, historical replays or continuous Yahoo watches, polls atomic snapshots every three seconds, plots equity, displays positions/decisions/fills, and links report exports. Existing finance MCP tools remain read-only data operations.

Workers survive browser, Node and MCP connection closure. Continuous watch advances across NYSE sessions until stopped or halted by data/execution/policy failure. `deploy/install_service.py` provides inspectable macOS launchd setup for runtime and web services. Runtime restarts preserve job records and mark unfinished work interrupted; automatic intraday portfolio recovery remains deferred. This is local single-user simulation infrastructure, not broker execution or cloud uptime guarantees.

Validation covers real stdio MCP discovery, independent-runtime execution, offline full-session reports, reconnecting clients, cancellation, bounded workers, token-protected runtime requests, artifact restrictions, restart labels and React polling. See [deployment and operation](deploy/README.md).

## Agent Loop Architecture

Chat now uses a bounded model → tool → observation → model loop through the existing LangChain structured-output chains. `backend/agent-loop.js` owns execution state, repeat detection and the six-tool-step limit; `backend/agent.js` supplies session context, MCP access, profiling and application adapters. React displays a concise action trace. Direct Finance workspace forms keep deterministic execution.

The model can inspect empty searches, choose alternate lookup tools, inspect company metadata and then request a report. Company briefs use a reusable resolver for name searches, fallback lookup, name/country/symbol checks and ambiguity handling, then expose reporting. Tool names are constrained per step; an empty search cannot authorize a guessed ticker. Identity fields are retained in model observations, while full reports remain available to React. Tool errors become observations rather than ending the entire investigation. Completion, clarification, incomplete reports, repeated actions, invalid planner output and the tool budget are explicit terminal states. A ready company or benchmark report completes its explicit goal immediately, avoiding an unnecessary final model call. Identical calls are not automatically retried. A workspace call is one loop action but may perform several bounded MCP calls internally.

A live Ollama/Yahoo run resolved FPT Corporation to FPT.VN in Vietnam and generated its research report. Validation includes alternate search after an empty result, report preservation, error recovery, repeat/step limits, invalid tools, isolated request state and API-compatible traces. Durable chat checkpoints, nested agents and external write actions are deferred. Trading background execution is implemented in the separate runtime described below. The old router remains available for injected legacy chains in tests; the default production chains use the loop.

### 1. Current State
- **Agent core**: `backend/agent.js` uses LangChain.js and local Ollama to route queries, execute tools, and handle stock comparisons and follow-ups.
- **API / UI**: Express serves `/query`, `/health`, `/memory/reset`, and `/memory/search`. React runs through Vite during development and is served by Express after a production build.
- **Memory**: Structured context travels with requests and is retained in browser session storage. SQLite keeps semantic conversation snippets per session, including entries from the previous Python backend.
- **Observability**: Each response returns latency, component timings, tool usage, approximate token counts, and stock planner traces. React displays these details.
- **Tests**: Node tests cover tools, memory, concurrency, agent behavior, and API contracts; React tests cover chat, context, reset, failures, and keyboard interaction.

## Proposed Next Release: Useful Tools with Verifiable Answers

**Status: yfinance data capability families exposed through MCP; all seven finance workspace workflows implemented; non-finance integrations remain proposals.** Build for the current local, personal-use assistant. Prioritize finance through `yfinance`, followed by expanded Open-Meteo and Open Library. Defer Frankfurter currency conversion until the finance foundation is reliable. Keep the Express API contract and React chat flow. The model should select tools and extract inputs; calculations, filtering, and factual results should come from application code and provider data.

### First: Close the Reliability Gaps

Recent failures exposed two distinct problems: the router interpreted a company name as arithmetic, and a stock provider rejected requests. More tools will magnify these problems unless each integration has a clear input and failure contract.

- Validate tool arguments before making requests. Ask a targeted clarification for missing or ambiguous inputs rather than inventing an amount, location, currency, or title.
- Keep errors attributable to the provider. Distinguish invalid input, no results, timeouts, and rate limits. Do not let the model turn failed requests into apparent factual answers.
- Include a source link and the relevant data date in answers. For forecasts, distinguish retrieval time from forecast time.
- Retain the existing timeout behavior. Add retries only for a demonstrated transient failure; do not retry access-denied responses.

**Acceptance:** mocked tests verify each failure path; conversation tests cover clarification replies and changes of topic. Existing stock and calculator regressions remain green.

### 1. Finance: Yahoo Finance through `yfinance`

**Pitch:** make company lookup, stock history, comparisons, and market-overview questions work through one focused data adapter. “Take-Two Interactive stock” should resolve to TTWO; “How is the stock market today?” should return a clearly labeled snapshot of selected benchmarks instead of asking for a company ticker.

**Architecture (implemented):** Express, LangChain.js, Ollama, and React remain the application stack. `backend/finance/server.py` exposes yfinance search, daily history, and quotes through the official Python MCP SDK. `backend/finance/client.js` uses the official JavaScript MCP SDK over stdio: initialization, tool discovery, validated tool calls, bounded timeouts, serialized requests, and subprocess shutdown. The backend creates one lazy connection; the standalone CLI also supports reuse by other local MCP hosts. Python requirements are pinned in `backend/finance/requirements.txt`. Remote HTTP hosting is deferred.

**Completed:** direct JavaScript stock HTTP calls have been replaced by MCP calls; offline protocol and agent tests cover discovery, tool execution, invalid arguments, provider failures, and process startup. A live TTWO quote succeeded. The Finance workspace now provides all seven workflows below, including benchmark snapshots and aligned adjusted-price comparisons. Request-local duplicate calls are reused; cross-request caching remains deferred.

**Smallest release:** ticker/company search, latest available daily prices, daily OHLCV history, and comparisons of up to four stocks. Use a fixed, disclosed US market basket (S&P 500, Nasdaq Composite, Dow Jones) for otherwise unspecified market-overview questions; clarify other markets. Retain symbol, exchange, currency, exchange timezone, observation date/time, and source in normalized results. Do not treat a daily close as a guaranteed live quote.

**Calculation rules:** calculate returns in application code, align comparison dates across symbols, and explicitly choose adjusted versus unadjusted prices. Label comparisons based on adjusted prices accordingly. Missing prices stay missing; do not substitute zero or calculate changes across unavailable observations. Cache repeated lookups briefly and identify cached observation times.

**Failure contract:** distinguish unknown symbols, empty histories, provider throttling/access failures, and adapter startup/timeouts. `yfinance` still depends on Yahoo availability; it cannot guarantee elimination of 403 or 429 responses. Stock requests now use the MCP adapter exclusively; report provider failures rather than silently falling back to another data path.

**Acceptance:** mocked adapter and Node integration tests cover company→ticker resolution, TTWO quotes, market-overview routing, session follow-ups, multiple currencies, non-trading days, missing observations, adjusted-price comparisons, and provider/process failures. A live smoke test verifies TTWO plus the benchmark basket. Existing API fields, stock plan traces, and React behavior remain compatible; setup instructions explain the new Python dependency.

**Currency follow-ups (implemented):** store the last stock quote in session metadata and expose `exchange_rate` through MCP. Convert its native price with Yahoo FX pairs such as `USDGBP=X`; show stock and FX observation dates separately. Currency changes do not trigger stock searches or overwrite the original price. Frankfurter is unnecessary for this quote-conversion feature.

**Broader yfinance capability review (MCP tools now implemented):** [official API reference](https://ranaroussi.github.io/yfinance/reference/index.html). The server exposes 18 bounded tools and `yfinance://capabilities`, including statements, holders, corporate actions, funds, options, markets, screening and short streaming snapshots. Chat discovers the selected tool schema and generates validated arguments. See [CAPABILITIES.md](backend/finance/CAPABILITIES.md) for full mappings, administrative exclusions and usage. The priority table below now describes richer product workflows on top of these APIs, not missing MCP endpoints.

| Priority | Candidate MCP capability | yfinance surface | Delivery requirement |
| --- | --- | --- | --- |
| Next | Market benchmark snapshot | Index `Ticker.history`; `Market.summary` | Disclose benchmark basket, exchange times, and missing observations. |
| Next | Company profile and fundamentals | `Ticker.get_info`, `get_fast_info` | Select useful fields; preserve absent metrics and currency units. |
| Next | Earnings dates and corporate actions | `get_earnings_dates`, dividends, splits | Separate scheduled dates from confirmed events; bound date ranges. |
| Later | Financial statements | Income statement, balance sheet, cash flow | Identify annual/quarterly periods and reported currencies; bound rows. |
| Later | Analyst estimates and holders | Price targets, estimates, institutional holdings | Identify observation periods and distinguish estimates from facts. |
| Later | ETF/fund details | `FundsData` | Return selected holdings and exposure with available dates. |
| Later | Sector discovery and screening | `Sector`, `Industry`, `screen` | Validate filters and cap result counts. |
| Deferred | Options and streaming | Option chains, `WebSocket` | Separate expiry/strike schemas and lifecycle work; no trading actions. |

**Product workflow delivery:** company research, comparison dashboard, earnings explorer, ETF overlap, explained screener, portfolio currency attribution and on-demand market morning brief are implemented. React provides charts, tables, source drill-down and partial-data warnings; `/finance/workspace` validates inputs and runs deterministic calculations through the existing MCP client. Offline tests cover calculations, failures, endpoint validation, chat routing and all seven forms; live smoke checks returned provider data for each workflow. Scheduled delivery, persistent portfolios and trading execution remain deferred. No Alpha Vantage integration is planned for this release.

**Source and usage:** [official yfinance repository](https://github.com/ranaroussi/yfinance). The library is open source and unaffiliated with Yahoo; its documentation describes research/educational use and Yahoo data as intended for personal use. Reassess data rights before commercial deployment.

### Deferred: Frankfurter Currency Conversion

**Pitch:** answer “Convert £100 to USD” and “What was the EUR/GBP rate on 1 June 2026?” with explicit amounts, currencies, and rate dates. This adds a useful finance capability without stock-feed dependencies or API keys.

**Smallest release:** one currency-conversion tool accepting an amount, source currency, target currency, and optional date. Fetch the rate, multiply in JavaScript, and round only the displayed result using the target currency's minor units. State that the result uses a reference rate and excludes bank fees. Show the returned rate date, including when the requested date has no published observation.

**Boundaries:** no live forex trading, bank transfers, exchange-rate charts, or inferred historical rates. Clarify ambiguous symbols such as `$` unless the conversation establishes the currency. Reject unsupported currencies and future historical dates before calculating. A simple bounded backend cache can reuse published rates; no separate cache service is needed.

**Acceptance:** tests cover GBP→USD, historical conversion, weekend dates, zero amounts, unsupported currencies, ambiguous `$`, and provider failures. A follow-up such as “Now in euros” retains the amount and source currency within its session.

**Provider:** [Frankfurter documentation](https://frankfurter.dev/). Free public access without a key; daily reference data. Use the current v2 API. Provider-specific rates have their own terms.

### 2. Open-Meteo: Forecasts and Air Quality

**Pitch:** extend the existing weather integration to answer “Will it rain in London tomorrow?” and “What is the air quality there?” Reuse location resolution instead of adding another weather provider.

**Smallest release:** a seven-day daily forecast with temperature range and precipitation probability, plus current AQI and its named scale. Resolve relative dates in the selected location's timezone. Store location coordinates and timezone for follow-ups; request only the variables needed for the question.

**Boundaries:** clarify ambiguous locations, keep Celsius as the existing default, and support explicit Fahrenheit requests. Forecasts are predictions; avoid guarantees about rain or claims that an AQI reading means an activity is medically safe. Defer travel planners and weather notifications.

**Acceptance:** tests cover tomorrow across timezone boundaries, Celsius/Fahrenheit, missing forecast observations, named AQI scales, unavailable data, and “What about tomorrow?” after a location-specific question. Preserve current-weather behavior and include Open-Meteo attribution.

**Provider:** [Open-Meteo documentation](https://open-meteo.com/en/docs) and [pricing](https://open-meteo.com/en/pricing). The hosted free tier is for non-commercial use with rate limits. Recheck terms before commercial deployment.

### 3. Open Library: Book Discovery

**Pitch:** provide grounded book and author searches: “Find books about reinforcement learning” or “Who wrote this title?” Return a small set of identifiable works rather than invented recommendations.

**Smallest release:** search by title, author, or subject; return up to five matches with title, author, first publication year when available, and an Open Library link. Use stable work identifiers to handle “Tell me about the second one.” Distinguish works from editions; missing descriptions or ISBNs must remain missing.

**Boundaries:** no bulk harvesting, full-text download promises, or claims that publication metadata establishes book quality. Cover images and recommendation ranking can follow after text search is reliable.

**Acceptance:** tests cover duplicate editions, ambiguous titles, absent authors/years, empty results, ordinal follow-ups, and HTTP 429. Identify the application in requests, cache repeated searches, and pace requests to the provider's published limit.

**Provider:** [Open Library API guidance](https://openlibrary.org/developers/api). No key; default limit is one request per second. Intended for human book discovery, not high-traffic commercial infrastructure.

### Delivery and Deferred Decisions

Each integration should be a focused change to JavaScript schemas, adapters, session context, and tests. Split an adapter into its own module when adding it makes `backend/tools.js` harder to review; avoid introducing a plugin framework. Add React presentation only when existing text responses cannot communicate the result clearly.

Release each tool after `npm test` and `npm run build` pass, followed by a live smoke test and a documented failure example. A successful API response alone is insufficient: verify routing, argument extraction, follow-up behavior, source attribution, and displayed results together.

Defer TMDB until entertainment features are a priority; its free use requires non-commercial use and attribution. See [TMDB's FAQ](https://developer.themoviedb.org/docs/faq). Finance work will focus on `yfinance`; adding other finance providers or paid subscriptions requires a separate scope decision.

Keep Redis, managed vector stores, background workers, and deployment infrastructure in the backlog until measured usage warrants them.

### 2. Upcoming Enhancements
1. **Planner & Memory Upgrades**
   - Pluggable embedding backends (local hashed encoder vs. OpenAI, Cohere, Instructor, etc.) with config-driven selection.
   - Administrative APIs/UI toggles to inspect/delete specific semantic entries, export conversation history, and show retrieved snippets inline.
   - Background cleanup jobs (age-based pruning, session archiving) so SQLite/pgvector stores stay lean.
   - Additional planners (weather workflows, multi-tool intents, reminders) using the same plan→act→reflect pattern introduced for stocks.

2. **Persistent Storage**
   - Replace browser session storage with Redis or another external store for structured metadata; move semantic embeddings to pgvector/SQLite per user.
   - Add TTL/retention policies per context block (weather < 24h, facts < 30d, reminders with due dates).

3. **Expanded Tests**
   - Network-mocked tests for each tool + LangChain follow-up classifier.
   - Broaden Express integration tests for multi-turn conversations and external service failures.
   - Front-end smoke tests (Playwright or Cypress) for the React UI.

4. **Chat UI Enhancements**
   - Streaming responses + typing indicators.
   - Toggle panels showing structured metadata, retrieved semantic snippets, and timing breakdowns per turn.
   - Mobile-friendly layout, theming, and keyboard shortcuts (Enter/Shift+Enter already available).

5. **Deployment Considerations**
   - Dockerize Node.js + React + Ollama (docker-compose, env templates).
   - Background workers for long-running tasks.
   - Document rate limits + fallback strategies in README.

### 3. Long-Term Ideas
- **Multi-user auth / session routing** with per-user memory stores and quotas.
- **Vector memory** backed by a managed vector DB (Pinecone, Weaviate) for richer semantic recall + RAG.
- **Tool orchestration / planning** via LangChain chains or a lightweight planner to coordinate multi-step tool usage.
- **LLM observability** dashboards: aggregate timings, errors, token usage across sessions for ops visibility.
