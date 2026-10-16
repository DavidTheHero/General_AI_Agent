# Roadmap

## Primary objective: discover a profitable edge, then expose the validated strategy through MCP

User clarification, 15 October 2026: begin with **US stocks/ETFs, daily or multi-day signals, free data first**. On **16 October**, the user removed the product-universe restriction: choose instruments based on an economic hypothesis and verifiable data, including other markets when their calendars, currencies, funding, settlement and roll mechanics can be represented correctly. Free data first and simulated execution remain in force. The platform is supporting machinery. The research objective is a repeatable net-of-cost trading advantage under explicit risk/capital assumptions, followed by a versioned, inspectable MCP strategy. Positive P&L from owning a rising market, a lower drawdown, and incremental signal value are separate outcomes. We cannot promise an edge exists in the tested data.

The next priority is empirical research on real observations; evidence development is no longer deferred behind more infrastructure or a larger catalog. The earlier intraday simulator cannot evaluate overnight strategies: it resets indicators and liquidates daily, while its dataset rules reject ordinary ETF distributions. Preserve those semantics and use a separate, explicitly labeled daily research path.

### First real-data pilot, preregistered before performance inspection

- Freeze a small liquid ETF universe: SPY, IEF, GLD. It is a retrospectively selected surviving universe, not a survivorship-free stock universe. Two hypotheses: SPY long/cash trend; positive relative momentum among these three ETFs. Test 126/189/252-session lookbacks, monthly completed-close decisions, next-session opening proxy execution, overnight holdings and no leverage. These adapt published trend/momentum ideas; they are not reproductions of a futures long/short paper and are not established edges.
- Acquire complete daily OHLCV, adjusted close and action columns for 2005–2022. Warm-up observations begin in 2005; training is 2006–2012; parameters freeze before validation over 2013–2022. **2023–2025 stays reserved and is not requested.** A genuinely forward paper period after freezing remains necessary because historical researcher knowledge cannot be erased.
- Rank configurations on training performance against the declared family benchmark; report every training/validation configuration and failure. Charge 5 bps per traded dollar, with 10/20-bps stresses. Use identical timing/cost/capital conventions for SPY passive and monthly equal-weight ETF benchmarks; cash earns zero. Report profit, CAGR, exposure, volatility, drawdown, turnover and benchmark excess separately.
- For initial feasibility only, use normalized fractional total-return proxy units derived from Yahoo adjusted close and adjusted open. This handles provider distribution-reinvestment assumptions without double-crediting dividends. It does **not** establish executable raw-share fills, actual dividend cash flows/payment dates, point-in-time revisions, spreads or market impact. Archive original adapter outputs, requested settings, metadata, checksums, quality/action counts and independently reconciled proxy ledgers.
- Quantify paired monthly benchmark excess with predeclared 12-month block resampling and a conservative correction across locally declared configuration/protocol pairs. Report assumptions, all attempts and external-search limitations. Positive estimates with uncertainty spanning zero remain inconclusive. Annualized log-return excess is a diagnostic, not factor-model alpha.

### Promotion to a strategy MCP

`trading_daily_research_start/status` expose bounded discovery work as background research. They must return `research_only` and preserve the final-period reservation. A research API endpoint is not evidence that a strategy works. A candidate can advance only after stable validation across parameters/regimes/costs, independent data replication, a locked final evaluation, raw-share corporate-action accounting and genuinely forward simulated observations. The eventual strategy MCP should expose its fixed version, exact data requirements/as-of, target proposal, risk limits, decision evidence and failure state; deterministic host code owns accounting/execution. Keep real brokerage execution outside scope.

### Data exploration priorities

Start with archived Yahoo daily ETF histories for no-key screening. Next cross-check promising candidates with independently acquired historical consolidated data; credentialed Alpaca historical SIP is a free-first option subject to the documented access rules. Explore SEC original filings for event/quality hypotheses and ALFRED vintages for macro filters only when public-availability timestamps and revision handling are implemented. Broad stock selection needs historical membership/delistings; short-horizon signals need reliable quotes and costs. Do not add features because they make an in-sample curve look better. See [verified data-source exploration](docs/EDGE_DATA.md) for official sources, coverage distinctions and prerequisites.

### Empirical delivery, 16 October 2026

The first real-data study is complete: 4,531 daily observations per ETF, six declared configurations, 32 reconciled attempts. Training selected SMA189 and momentum126 before validation. At 5-bps modeled one-way costs, 2013–2022 net CAGR was approximately **8.05% versus 11.83% SPY** for trend, and **5.88% versus 4.72% equal-weight** for momentum. Momentum's advantage fell to approximately **0.25 percentage points at 20 bps**, with greater volatility/drawdown than its reference and uncertainty spanning zero. Assessment: **inconclusive; no edge established**. [Full evidence, costs and provenance](docs/EDGE_PILOT.md)

The initial implementation failure and original snapshots remain recorded. A corrected acquisition now preserves structured metadata without triggering lazy intraday requests, action counts and an exact Python source bundle. Metadata can contain retrieval-time information; signals use only the requested historical prices. The fresh snapshot caused tiny adjusted-price differences and unchanged rounded conclusions; this is not independent-provider replication.

MCP `trading_daily_research_start/status` and the daily worker are implemented. The existing idle runtime was refreshed, and a real default-runtime job survived MCP disconnect/reconnect, completed32 reconciled attempts, matched CLI metrics exactly on the identical checksummed snapshot and produced report/plot artifacts. The UI exposes a daily job receipt and generic cancellation. **2023–2025 historical price paths remain unrequested.**

Checks passed: **108 Python tests, 83 backend tests, 31 React tests**, production build and diff checks. These verify code and protocol behavior; they are not statistical market evidence. The daily pilot is a fixed training/validation split with chronological subperiod diagnostics, not rolling walk-forward retraining. Raw-share action/payment-date accounting, independent-source replication, locked final evaluation and forward paper observations remain promotion blockers.

The [bounded sector-momentum protocol](docs/NEXT_EDGE_PROTOCOL.md) is now **complete, inconclusive**. One real MCP study acquired 5,787 daily bars for each of nine sector ETFs plus SPY over 2000–2022 and completed 24 reconciled attempts. The predeclared L252/K3 primary earned 12.60% validation CAGR versus 11.83% SPY at 5-bps costs; at 20 bps it earned 11.78% versus 11.81%. Uncertainty spans zero and performance depends on the 2021–2022 segment. All four configurations are retained, without replacing the primary with the 16.61% validation-best concentrated sensitivity. XLF's 2016 in-kind distribution is represented by a synthetic split in Yahoo and remains an explicit accounting blocker. [Results, source review, costs and provenance](docs/SECTOR_EDGE_PILOT.md)

`trading_sector_research_start/status` now expose that exact frozen research protocol through independent runtime workers; final-period/parameter overrides are rejected. A real MCP disconnect/reconnect run completed, and the dashboard receipt displays primary benchmark comparisons, costs, drawdown, validation dates and unresolved limitations. The reserved 2023–2025 price paths remain unrequested. Current checks: **127 Python, 86 backend and 32 React tests**, production build and diff checks. Positive historical profits remain research leads; no profitable edge has been established or promoted.

### Broader product selection and next falsification

The [product review](docs/PRODUCT_SELECTION.md) compares global/multi-asset ETFs, individual stocks, futures, FX and crypto under current source and accounting constraints. The next [frozen global reversal protocol](docs/GLOBAL_REVERSAL_PROTOCOL.md) covers SPY, IWM, QQQ, EFA, EEM, IEF, TLT, GLD and DBC: US equity styles, foreign equities, Treasuries, gold and commodity-futures exposure. The ETF wrapper is an implementation choice, not a permanent product restriction.

Test weekly volatility-normalized short-term loser recovery, four configurations with L5/K3 primary, continuous validation holdings and expanding prior-only allocation references. Record all attempts and include at least fourteen known configurations in the research lineage. Required acceptance: causal weekly schedule/next-open execution, independent reconciliation, unchanged monthly behavior, continuous fold-boundary capital, exact data provenance and bounded disconnected MCP execution. This extends the economic question beyond monthly momentum; it is not evidence of an edge before testing. Keep the original reserved price paths untouched. Futures/FX/crypto require separate contract, funding, calendar and execution support before valid simulations.

**Completed:** the [broader weekly reversal study](docs/GLOBAL_REVERSAL_PILOT.md) acquired 4,028 daily observations per instrument and completed 31 reconciled attempts through MCP. Its unchanged primary earned **4.58% versus 5.46% equal-weight** validation CAGR at 5-bps costs, with greater volatility/drawdown. At 20 bps it earned **−5.67%**, and positive excess is rejected against both references under that stress. Base-cost uncertainty spans zero; overall `inconclusive`, not advanced. All four configurations and the failed economic hypothesis remain recorded. Source/declaration capture, causal reference weights, uninterrupted fold capital, exact prior monthly replay and disconnect/reconnect were verified. **153 Python, 90 backend and 33 React tests**, production build and diff checks pass. The reserved prices remain unrequested; selection is now unrestricted by product family, with accounting/data prerequisites explicit.

## Simulated strategy research platform — design and delivery plan (2026-10-15)

This section supersedes the trading claims below. Trading remains simulated. The objective is a reproducible research workflow before a larger strategy catalog. A successful backtest is not evidence of an economic edge by itself.

### Verified starting point

Code inspection covered `data.py`, `calendar.py`, `strategies.py`, `engine.py`, `portfolio.py`, `metrics.py`, `runner.py`, `runtime.py`, `mcp_server.py`, the Node MCP client/API and React Trading desk. Baseline verification: all 43 Python tests and three Node trading integration tests passed. These include replay/watch equivalence, real stdio MCP discovery, disconnect/reconnect, cancellation, interrupted positions and runtime restart labels. Existing docs were not used as proof.

Existing capabilities: strict long-only target-weight proposals; completed-bar policy inputs; next-open whole-share fills; commissions/slippage; host position/gross/daily-loss/error controls; XNYS holidays/early closes; fail-closed missing/invalid/duplicate bars; delayed Yahoo polling; SQLite job ownership, independent workers and atomic reports. The existing chart benchmark is fractional and cost-free, and must remain labeled as such; research comparisons need separately executed, cost-matched benchmarks.

Correctness gaps: conflicting duplicate events are ignored; direct engine calls can bypass bar validation; no independent fill-ledger reconstruction. Research gaps: no immutable datasets/raw provider outputs/checksums, registry versions, attempt ledger, chronological selection, protected final period, sensitivity or cost stress. Yahoo downloads discard action/adjustment columns and cannot establish point-in-time universe membership, delisting completeness, trade/quote liquidity or historical availability. All symbols currently use XNYS; other calendars and currencies need explicit adapters. Temperature zero does not establish LLM determinism or remove historical training contamination.

### Boundaries and module contracts

- `registry.py`, `strategies.py`, `config.py`: versioned strategy descriptions and validated parameters; a policy consumes completed observations and returns the shared typed `Decision` (one weight per configured symbol plus a short explanation). Strategies cannot execute orders.
- `data.py`, `datasets.py`: capture provider adapter responses before normalization, preserve action columns and request settings, write content-addressed read-only datasets, verify checksums on use, and report completeness/duplicates/actions/invalid data. Aggregated OHLCV bars are never described as trades or quotes. Unavailable observations are errors, never synthesized. Synthetic fixtures are visibly labeled.
- `engine.py`, `portfolio.py`, `reconciliation.py`: deterministic ordering, risk enforcement, fill/accounting state and independent reconstruction. No shorting, leverage, broker orders or fabricated closing fills. Loss stops operate on observed bar closes and execute at a subsequent available open; they cannot guarantee a maximum realized loss.
- `research.py`: immutable preregistered experiment specifications, expanding chronological training/validation folds, explicit candidate attempts, shared capital/costs/data, separately executed cash and buy-and-hold benchmarks, parameter comparisons and stress costs. Reserve the final sessions before selection. Final evaluation requires a completed parent validation experiment with the identical protocol, freezes selection, and consumes the dataset holdout once. Record failures and cancellations as attempts, not missing rows.
- `runtime.py`: persistent ownership, concurrency/work budgets, worker processes and interruption reconciliation independent of MCP/client lifetime. Restart retains last artifacts and marks interrupted work; automatic intraday resume remains unsupported rather than silently replaying positions.
- `mcp_server.py`, Node trading client/API: bounded discovery/validation, dataset creation/inspection, experiment submit/status/list/compare/cancel. Submit returns a job/experiment ID immediately; status includes dataset and artifact references. MCP is a control plane, not the worker.
- React: presentation and explicit user choices only. Show source, dataset/protocol IDs, training/validation/final labels, costs, drawdowns, benchmark methodology, decisions/fills and operational/data failures. Reject comparisons with different data or research protocols.

### Strategy registry v1

Start with long-only intraday trend following (fast/slow completed-close averages; persistence hypothesis), mean reversion (rolling completed-close z-score with entry/exit hysteresis; temporary displacement hypothesis), and opening-range breakout (completed initial range followed by a close above its high; opening information/continuation hypothesis). Each registry entry must expose version, parameter bounds, observation requirements, warm-up and failure conditions. These are research hypotheses, not asserted edges. Reset policy state each session and liquidate on the scheduled final observed close; the intraday horizon is explicit.

Preserve SMA/momentum/buy-and-hold compatibility. Treat Ollama as experimental under the identical host constraints. Save exact requests/responses and configured model identity; disclose that a configured model tag is not a verified weights digest, historical facts may be in training data, and repeated runs may differ. Unsupported shorts require borrow availability, recalls, fees and locate rules; leverage needs financing/margin/liquidation; options need contract lifecycle, exercise and point-in-time chains; execution-sensitive strategies need timestamped trades/quotes, spreads, depth and latency. Do not add these strategies before their data and accounting exist.

### Phases, acceptance and evidence

1. **Audit and design (baseline complete).** Acceptance: executable inventory and verified baseline above; this design precedes behavior changes. Artifact: this roadmap. Limitation: network history and profitable edge are not established by offline tests.
2. **Dataset and execution integrity.** Acceptance: original adapter-level responses and normalized bars are separately preserved, timestamps/settings/provenance/checksums/quality accompany every dataset, corrupted/gapped/duplicate/action-incompatible data cannot enter an experiment, conflicting events fail, independent ledgers reconcile. Tests: known-answer cash/P&L/cost fixtures, generated randomized portfolio sequences, future-data perturbations and replay/stream equality. Artifacts: immutable manifest/raw/normalized files and reconciliation records. Limitation: yfinance exposes processed DataFrames, not original Yahoo wire bytes; record this honestly. Reject corporate-action sessions until accounting handles them.
3. **Versioned strategies and reproducible experiments.** Acceptance: discover/validate three hypotheses plus experimental LLM; persist every candidate/period/cost attempt before evaluation; train strictly before validation, reserve an untouched final period, freeze selection before a single final evaluation; match benchmark execution/capital/cost constraints. Tests: deterministic reruns, fold boundaries, failed attempts, parameter/cost sensitivity, final-period access guard and independent reconciliation. Artifacts: protocol/environment/source hashes, attempt JSONL, per-attempt ledgers, validation and final summaries. Multiple-testing: disclose candidate/attempt counts and a conservative family-wise bound on a one-sided session sign test; do not claim a calibrated probability of overfitting or independent samples. Synthetic/short/dependent/contaminated results remain inconclusive.
4. **Durable MCP and dashboard.** Acceptance: bounded tools return exact IDs and references, workers survive MCP disconnect, cancellation and restart retain partial state and failure labels; UI compares compatible experiments and distinguishes reserved/final periods and unavailable metrics. Tests: real MCP/runtime round trip, reconnect/cancel/restart, schema/budget rejection, React source/quality/cost/period/failure rendering. Artifacts: inspectable local job records and experiment exports. Limitation: local single-user service; no HA, automatic portfolio resume or live routing.
5. **Evidence review and later extensions (deferred).** Acceptance: a sufficiently long, licensed, point-in-time dataset, preregistered economic rationale and costs, genuinely forward paper observation, regime/dependence-aware inference and independent review before describing an edge as supported. Future work: alternate calendars/providers, universe/survivorship controls, order/quote execution models, cryptographic LLM weights identity, formal PBO/deflated-Sharpe methods with justified assumptions, and restartable intraday checkpoints. No strategy catalog expansion until phases 2–4 work end to end.

### Research interpretation and limitations

Shared OHLCV cannot identify intrabar path, bid/ask, market impact, queue position or executable size. Fixed basis-point stress is a scenario, not a liquidity model. Training/validation metrics are selection evidence; final metrics are out-of-sample only relative to this recorded protocol, not all human research. Dataset-wide holdout reservation prevents accidental local reuse but cannot detect outside research or copied datasets. Explicit candidate lists provide bounded parameter sensitivity; the platform does not infer a complete search space. Every observed outcome must be labeled **supports**, **inconclusive**, or **rejects** under disclosed criteria; no edge is currently supported.

Methodology references: [Bailey et al., The Probability of Backtest Overfitting](https://www.carmamaths.org/resources/jon/backtest2.pdf) motivates recording the search, [Glasserman and Lin, LLM look-ahead bias](https://arxiv.org/abs/2309.17322) motivates experimental LLM labeling, and [yfinance history implementation](https://github.com/ranaroussi/yfinance/blob/main/yfinance/scrapers/history.py) distinguishes adapter processing from original wire data. Implementation evidence below must be updated after checks pass; planned behavior is not a completion claim.

### Delivery evidence (phases 2–4 implemented)

- Dataset/raw archives, registry v1, host event validation and independent reconciliation are implemented. Yahoo polling/replay also preserves each adapter response and error under `source-responses/`, with a durable checksum index; that archive is explicitly separate from a validated research dataset. Nonfinite raw values retain distinct tags. Corporate-action sessions and unsupported calendars fail closed in research.
- Bounded studies persist protocols/environment/source hashes, every started/completed/failed/cancelled attempt, fold selection/sensitivity and matched benchmark comparisons consistently in SQLite, JSONL and per-attempt artifacts. Shared observation fingerprints prevent identical reacquisition from resetting a consumed holdout. Final evaluation checks the parent's software environment as well as its protocol. Annualized research estimates are withheld below 30 completed sessions. Crash reconciliation marks abandoned attempts/experiments interrupted without replay, retains consumed holdouts and appends idempotent recovery events.
- Runtime/MCP/Express expose the workflow; React displays registry/parameters, dataset quality, comparisons, period boundaries, costs/drawdowns and bounded decision/fill/reconciliation evidence. Existing simulation controls remain available. The running pre-change service was not restarted or its jobs disturbed; restart the runtime to load these new endpoints.
- Final checks passed: **84 Python tests**, **79 Node backend tests**, **30 React tests**, `npm run build` and `git diff --check`. Coverage includes known answers, generated ledger invariants, future-final-data perturbation, replay/stream equality, data corruption/actions/gaps, source revisions/staleness, cancellation, real stdio MCP disconnect/reconnect and restart reconciliation. These are correctness checks, not market-performance evidence.
- Reproducible offline artifact: `artifacts/trading/research-verification-release-20261015/verification.json`, with original dataset, validation/final request JSON, manifests, protocol/environment hashes, 46 attempt ledgers and final results. All **46/46** reconciled. Run `.venv/bin/python -m examples.research_workflow --output artifacts/trading/<new-directory>` to reproduce observations and metrics (acquisition timestamps and IDs intentionally differ). Synthetic final net return was approximately 0.527%, versus 0.656% for the matched benchmark; this has no empirical market interpretation. Assessment: **inconclusive**.

Remaining limitations: no live Yahoo availability or real Ollama performance was established in this delivery; no original Yahoo wire-byte capture, point-in-time universe, delisting/borrow/FX/action accounting, quote/liquidity model, calibrated dependence-aware edge test, authenticated LLM weights identity or automatic portfolio resume. Cross-study comparison intentionally requires the identical declared protocol; strategy/parameter comparisons use a shared study. Fold scores reset common capital and sum excess percentages as selection scores, not a compounded deployment path. Raw archive retention/disk quotas and continuous-job history compaction need an explicit policy. Corrupt persisted metadata requires inspection/repair rather than guessed recovery. Phase 5 remains deferred, and **no strategy edge is supported**.

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
