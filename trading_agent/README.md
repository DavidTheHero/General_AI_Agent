# Intraday Trading Agent

A modular Python framework for autonomous **paper simulations** over NYSE sessions. It ingests Yahoo Finance OHLCV, runs configurable rule or local AI policies, accounts for positions and execution costs, and writes executive reports and analytical charts automatically. It supports direct CLI execution and integration with the Node chat agent and React trading dashboard through a dedicated MCP server and independent runtime.

## Install and run

From the repository root, using Python 3.11+:

For Windows PowerShell, follow the [repository setup](../README.md#quick-start) and replace `.venv/bin/python` in this guide with `.\.venv\Scripts\python.exe`. For example:

```powershell
.\.venv\Scripts\python.exe -m trading_agent demo
.\.venv\Scripts\python.exe -m unittest discover -s trading_agent/tests -v
```

See [foreground Windows operation, shutdown and interrupted-job recovery](../deploy/README.md#windows-foreground-operation). macOS launchd remains available separately.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .

# Offline, reproducible full-session demonstration. Clearly labeled synthetic data.
.venv/bin/python -m trading_agent demo

# Real Yahoo bars; defaults to the latest completed NYSE session.
.venv/bin/python -m trading_agent backtest --config examples/trading_sma.json

# Explicit inclusive session dates, subject to Yahoo's intraday retention limits.
.venv/bin/python -m trading_agent backtest --start 2026-10-13 --end 2026-10-14

# Poll the active/upcoming session through close and generate its report.
.venv/bin/python -m trading_agent watch --config examples/trading_sma.json --sessions 1

# Keep watching future sessions until stopped.
.venv/bin/python -m trading_agent watch --config examples/trading_sma.json --continuous

# Local AI decisions: start Ollama and pull this model first.
ollama pull llama3.1:8b-instruct-q4_K_M
.venv/bin/python -m trading_agent backtest --config examples/trading_ollama.json
```

The installed `intraday-agent` command accepts the same arguments. Commands print progress on stderr and a JSON summary with the report path on stdout. Exit code `0` means a completed run; `2` means invalid input, incomplete data, or policy failure. Set `--output /path/to/new-directory` to choose the report destination. Nonempty output directories are rejected to preserve earlier runs. Without it, reports use a unique directory under `artifacts/trading/`.

The SMA example needs no model. The Ollama example makes one structured model decision per completed bar, so a historical replay may take several minutes. A zero-weight decision keeps cash; the framework does not force the model to trade.

## Modules and agent loop

```text
Calendar + Yahoo/synthetic DataFeed
    -> completed, ordered bars
    -> execute previously queued targets at the next bar open
    -> observe portfolio and completed price history
    -> Policy.decide(Observation)
    -> validate weights and apply risk limits
    -> queue targets for a later bar
    -> scheduled closing liquidation
    -> metrics, executive report and charts
```

| Module | Responsibility |
| --- | --- |
| `config.py` | Strict JSON configuration, numeric bounds and supported symbols/intervals. |
| `calendar.py` | NYSE holiday, daylight-saving and early-close schedule. |
| `data.py` | Yahoo ingestion, UTC normalization, completed-bar selection and missing-data checks. |
| `datasets.py` | Immutable adapter responses, normalized datasets, SHA-256 manifests and quality reports. |
| `registry.py`, `strategies.py` | Versioned hypotheses and parameters; trend, mean reversion, opening breakout, legacy policies and experimental Ollama. |
| `research.py` | Recorded attempts, chronological folds, reserved final tests, matched benchmarks and cost stress. |
| `reconciliation.py` | Independent fill/cash/position/cost/valuation reconstruction. |
| `portfolio.py` | Cash, whole-share inventory, average cost, fills, fees and realized P&L. |
| `engine.py` | Autonomous per-bar loop, next-open execution, risk stops and immutable history. |
| `metrics.py` | Portfolio/benchmark returns, drawdown, costs, exposure, turnover, realized/unrealized P&L and daily statistics. |
| `runner.py` | Multi-session replay and near-real-time polling with automatic reports. |
| `reporting.py` | Deterministic evidence-based executive narratives, PNG charts and audit ledgers. |
| `cli.py` | Runnable jobs and output-directory management. |
| `runtime.py` | Token-protected loopback job service, durable SQLite registry, worker lifecycle and artifact access. |
| `mcp_server.py` | Bounded simulation, registry, dataset and experiment tools over the independent runtime. |

## Integrated execution

Install MCP support with `.venv/bin/python -m pip install -e '.[mcp]'`, then run `npm run trading:runtime` alongside `npm run dev`. Open **Trading desk** or ask chat to run a synthetic demo. For continuous operation and process supervision, see [deploy/README.md](../deploy/README.md).

The MCP server is a control plane over local HTTP; the runtime owns worker processes and writes job status independently of chat or browser connections. Each tool call returns quickly without waiting for a trading session. Dashboard polling reads atomic bar snapshots containing observed equity, holdings, recent decisions and fills. Completed reports remain available through an explicit artifact allowlist. Jobs and reports persist on disk. This is an application-level job API, not an implementation of the optional MCP Tasks protocol.

Normal cancellation requests a partial report without inventing liquidation. If the runtime dies, workers detect the closed parent pipe and exit; on restart unfinished registry entries become **interrupted**. Inspect their saved evidence and explicitly create a new run. Jobs are not silently resumed, and the service supervisor restarts the service rather than recreating portfolio state. Yahoo failure limits and policy-error halts still stop continuous runs. Keep the machine awake, connected, and Ollama running for AI policies.

## Reproducible research workflow

For the current objective—finding a daily/multi-day net-of-cost edge—start with the [real-data pilot report](../docs/EDGE_PILOT.md) and [data-source assessment](../docs/EDGE_DATA.md). The intraday workflow below retains its original daily-liquidation semantics.

The separate daily research worker tests a frozen SPY/IEF/GLD universe, two monthly signal families and at most six declared configurations. It preserves overnight **normalized total-return proxy units**, validates daily coverage/actions/provenance and independently reconciles every attempt. Historical adjusted prices are revised and are not raw tradable shares; this worker cannot place broker orders or supply a validated operational strategy. Its current promotion status is `research_only`.

Run the default registered study through MCP:

```json
{"name":"trading_daily_research_start","arguments":{"research":{}}}
```

It immediately returns a job ID. Use `trading_daily_research_status` with `{"job_id":"<returned ID>"}`; use the existing `trading_stop` for cancellation. Local HTTP equivalents are `POST /trading/daily-research` with `{}`, `GET /trading/daily-research/:id`, and `POST /trading/jobs/:id/stop`. A daily job dashboard link shows a receipt with evidence status, final-period guard and report artifacts. The complete dataset, attempt ledgers, protocol and source snapshot remain local. Closing MCP does not stop the worker.

For the separate [frozen nine-sector study](../docs/NEXT_EDGE_PROTOCOL.md), call `trading_sector_research_start` with `{"research":{}}`, then `trading_sector_research_status` with its returned `job_id`. Equivalent HTTP routes use `/trading/sector-research`. The four configurations, primary L252/K3, dates, capital and cost scenarios are fixed; overrides that change the declaration are rejected. Cancellation still uses `trading_stop`. Its dashboard receipt compares the primary with both benchmarks across costs, shows drawdown and validation dates, and preserves operational blockers. [Actual inconclusive result](../docs/SECTOR_EDGE_PILOT.md)

An offline CLI submission uses `python -m trading_agent.sector_research` with the same flags below and `--request examples/sector_edge_research.json`. It archives the declaration and exact source before acquiring development data, and reuses only checksummed snapshots with identical request settings. A new output/root and unused 32-hex experiment ID keep prior attempts intact. A new download can differ from the archived provider revision; it is not an exact replay. Both daily workflows are adjusted research proxies, not broker-order or validated strategy interfaces.

The [global weekly reversal study](../docs/GLOBAL_REVERSAL_PROTOCOL.md) uses `trading_weekly_research_start({"research":{}})` and `trading_weekly_research_status({"job_id":"<returned ID>"})`, or `/trading/weekly-research` HTTP routes. The worker module is `trading_agent.weekly_research`; its CLI request example is `examples/weekly_reversal_research.json`. It fixes nine instruments, four configurations, weekly completed-close/next-open timing and expanding prior-only allocation references. Validation capital/holdings continue across folds. All 31 attempts remain auditable; cancellation uses `trading_stop`. [Completed results and replay evidence](../docs/GLOBAL_REVERSAL_PILOT.md). This is a batch `research_only` job, not a live weekly portfolio service.

For direct execution with explicit settings, from the repository root:

```bash
.venv/bin/python -m trading_agent.daily_research --request examples/daily_edge_research.json --root artifacts/trading/daily-research --output artifacts/trading/daily-research-output --experiment-id 20261016000000000000000000000001
```

Use a new experiment ID and output directory for another study. Exact checksummed development snapshots with structured metadata can be reused, with the original retrieval time disclosed. The tool never silently substitutes a shorter date range or another provider. Original provider metadata can contain retrieval-time information; policies consume only the requested historical price series. Lazy intraday metadata fields are explicitly omitted to avoid unrelated requests.

Defaults use 2005 warm-up, 2006–2012 training, 2013–2022 validation and reserve **2023–2025 historical price paths without requesting them**. Training selects one lookback per family before validation; the other validation configurations are reported as sensitivity, not reselection. This pilot is one chronological split with two-year validation diagnostics, not rolling retraining. Exact Python source is copied into each study and verified against recorded hashes. Exports include `daily-study.json`, `data-manifest.json`, `report.md` and `performance.png`.

The first real study earned positive historical proxy returns but established no edge. Momentum's extra return over its diversified benchmark came with higher volatility/drawdown and broad uncertainty. Neither an additional rerun nor a new MCP endpoint counts as independent market evidence. Promotion needs an independent data check, raw-share distribution/payment-date accounting, a locked final evaluation and genuinely forward simulated observations.

Open **Trading desk → Strategy research** after starting the current runtime. Existing running services must be restarted to load newly installed endpoints. The UI and MCP use the same workflow:

1. Discover `trading_strategies` and validate exact parameters with `trading_validate_strategy`. Versions currently equal `1.0.0`. Trend following uses completed fast/slow averages; mean reversion uses a rolling population z-score with position-dependent entry/exit; opening breakout waits for a completed initial range and later close above its high. All reset each session.
2. Submit `trading_dataset_create` with `dataset: {source, symbols, start, end, interval, seed}`. Dates are inclusive; `source` is `synthetic` or `yahoo`. This returns a durable job ID. Poll `trading_status`, then use its `report.dataset_id` with `trading_dataset_inspect`. Original dates/intervals are retained. Gaps, invalid data, unsupported sessions/currencies and corporate actions invalidate research; no values are filled.
3. Submit `trading_experiment_start` with an `experiment` matching the example below. The exact symbols and interval must match the dataset. Persisted attempts cover each declared candidate, chronological training/validation fold and cost scenario, including failures. Fold training expands forward; all validation dates precede the reserved final dates. Each fold resets the declared capital, and each session closes positions. Parameter sensitivity scores sum validation excess percentages; they are explicitly **not a compounded portfolio return**.
4. Poll `trading_experiment_status` using `job_id` equal to the returned experiment ID. Inspect per-attempt metrics and `trading_experiment_attempt` for bounded recent equity/drawdown, decisions, accepted targets, fills and reconciliation. The complete local ledger remains at its `artifact_ref`. `trading_experiment_compare` accepts 2–6 records only when dataset, protocol, software environment and evaluation period match. Strategies and parameter variants within a study appear together in its attempts/sensitivity table.
5. After reviewing validation, request a separate final experiment using the **unchanged parent specification**, `finalize: true`, and `parent_experiment_id`. Selection is frozen from development data, with no reselection on final results. A transactional reservation consumes the final period once, including if evaluation is interrupted. Identical reacquisitions share the holdout guard through an observation fingerprint. Changing the reserved final split or creating new selection studies after opening it fails. External research or modified/copied datasets cannot be fully policed.
6. Cancel through `trading_experiment_cancel`; partial evidence remains available. MCP/browser disconnection does not cancel a worker. Runtime restart marks abandoned experiments/attempts interrupted and preserves the last atomic portfolio snapshot; uncertain work since that snapshot is not reconstructed or replayed.

```json
{
  "dataset_id": "<exact 64-character dataset SHA-256>",
  "config": {"symbols": ["SPY"], "interval": "5m", "initial_cash": 100000,
             "costs": {"commission_bps": 1, "slippage_bps": 2, "fixed_fee": 0}},
  "candidates": [
    {"kind": "trend_following", "version": "1.0.0", "fast_window": 3, "slow_window": 12},
    {"kind": "trend_following", "version": "1.0.0", "fast_window": 5, "slow_window": 20},
    {"kind": "mean_reversion", "version": "1.0.0", "slow_window": 12, "entry_z": 1.5, "exit_z": 0.25},
    {"kind": "opening_range_breakout", "version": "1.0.0", "opening_range_bars": 3}
  ],
  "train_sessions": 3, "validation_sessions": 2, "final_sessions": 2,
  "cost_multipliers": [1, 2], "finalize": false
}
```

`trading_datasets` and `trading_experiment_list` default to 20 records (maximum 50). At most two workers run concurrently. Studies allow at most 12 distinct candidates, 3 cost scenarios, 160 attempts and 250,000 evaluated symbol-bars. Excessive work is rejected explicitly; dates, symbols or intervals are not silently reduced. Study IDs, protocol/environment hashes, raw data, quality and ledgers live under `artifacts/trading/runtime/research/` by default. Dataset files are read-only and verified on every load. Acquisition failures keep original adapter responses and a checksummed failure record under `datasets/acquisitions/`.

For direct offline verification, run `.venv/bin/python -m unittest discover -s trading_agent/tests -v` and `.venv/bin/python -m examples.research_workflow --output artifacts/trading/my-research-verification` (use a new directory). The synthetic example exercises immutable acquisition, all three hypotheses, a trend parameter variant, validation and one final evaluation. Workers can also be invoked with `.venv/bin/python -m trading_agent.research --request request.json --root artifacts/trading/research --output artifacts/trading/research-output --experiment-id <32-character hex ID>`, where the request wraps the dataset or experiment as `{"mode":"dataset","dataset":{...}}` or `{"mode":"experiment","experiment":{...}}`.

Research buy-and-hold benchmarks use the same whole-share engine, next-open timing, starting capital, gross/position limits, fees/slippage and scheduled liquidation; the cash benchmark earns zero. Legacy simulation charts retain their disclosed fractional, cost-free benchmark. OHLCV is aggregated data, not trades or quotes: spreads, intrabar path, market impact and queue priority are unavailable. Raw captures preserve the DataFrame returned by yfinance before local processing, including actions/adjusted-close columns; original Yahoo HTTP bytes are unavailable, and yfinance itself may process data.

Every result reports **inconclusive**, **rejects** or **supports** as an evidence vocabulary. This implementation never automatically declares an edge supported. Synthetic tests establish mechanics only; validation selects configurations. A completed real final sample of at least 20 sessions that fails to beat the matched benchmark in every declared cost scenario rejects that recorded positive-excess expectation. Other results remain inconclusive. Candidate/attempt counts and a conservative Bonferroni bound for a one-sided session sign test disclose search risk, but dependence, short samples and unrecorded searches prevent calibrated significance claims. LLM evaluations preserve exact prompt/response, while model tags remain unverified identities; historical contamination and nondeterminism remain unresolved. Additional point-in-time data, independent forward evidence and review are required before a supported edge claim.

## Configuration and policy behavior

See `examples/trading_sma.json` and `examples/trading_ollama.json`. Unknown configuration fields, nonfinite numbers, duplicate tickers, non-USD portfolios and invalid windows fail validation.

- `symbols`: explicit Yahoo tickers, up to ten. Use USD instruments compatible with the US session calendar. Non-USD quotes are rejected instead of silently mixed.
- `interval`: `1m`, `2m`, `5m`, `15m`, `30m` or `60m`. A final shorter bar ends at the scheduled close.
- `strategy.kind`: `sma` compares fast/slow means; `momentum` compares the latest close with the lookback's first close; `buy_and_hold` proposes an intraday allocation after the first completed bar; `ollama` returns validated weights and a concise decision description.
- `strategy.target_gross_weight`: maximum requested invested fraction. Active rule signals share it equally. The host applies this ceiling to model decisions too.
- `risk.max_position_weight`: caps requested weight per instrument. Actual marked weights can drift after execution.
- `risk.daily_loss_limit`: measured against session starting equity at completed-bar closes. Breach latches a halt and requests liquidation at the next open; gaps can exceed the threshold.
- `risk.max_consecutive_decision_errors`: failed or invalid policy outputs initially hold positions; reaching the limit halts the policy and queues liquidation.
- `costs`: buy/sell slippage and commissions in basis points, plus an optional per-fill fixed fee. Cash constraints can reduce buy quantities. Unaffordable exit costs produce an explicit incomplete run.

Ollama receives at most 60 recent bar records across all symbols, plus exact first/latest/mean close and return over the configured lookback. This bounds model context even with many symbols and long windows.

Policies reset each session and warm up using that session's observed bars. No indicator reads later bars. Portfolio cash carries across completed sessions; positions are flattened at close.

## Time and data semantics

Sessions normally run **09:30–16:00 America/New_York**, following EST/EDT automatically. Holidays are skipped and official early closes shorten the day. Timestamps are stored in UTC; charts display New York time.

Historical jobs accept completed sessions only. Yahoo limits intraday lookback, and availability differs by interval and instrument. Empty or incomplete sessions are errors, not zero prices or zero returns. The framework never interpolates missing bars. Split-containing downloads are rejected; intraday dividend entitlement, taxes and interest are not modeled. See the [yfinance history implementation](https://github.com/ranaroussi/yfinance/blob/main/yfinance/scrapers/history.py) and [exchange calendar documentation](https://pypi.org/project/exchange_calendars/).

Yahoo requests are checked before downloading or starting an explicitly dated background backtest:

| Interval | Preflight limits |
| --- | --- |
| `1m` | Automatically split into seven-day requests, within approximately the last 30 days. |
| `2m`, `5m`, `15m`, `30m` | Approximately the last 60 days. |
| `60m` | Approximately the last 730 days. |

These checks use the pinned yfinance implementation and observed Yahoo errors; the provider remains authoritative. The downloader batches retained minute ranges sequentially, trims provider overlap to each exact window, and merges ordered bars without filling gaps. Each instrument records batch dates and row counts in report provenance, and worker logs show batch progress. Seven-day chunks remain below Yahoo’s eight-day request limit across daylight-saving changes. A batch failure fails the download rather than returning a shorter range. Batching cannot retrieve expired January–October minute history. Choose recent dates or explicitly select hourly bars for a longer replay. The application preserves requested dates and intervals. Synthetic demos are exempt from Yahoo limits. Saved-job cards display provider failure reasons; form errors remain visible during polling.

`watch` is **delayed-bar event-time replay**, not a live broker execution system. By default it polls every 60 seconds and processes bars ending at least 900 seconds before the polling clock. Configure `data_lag_seconds` for the provider; setting it to zero does not guarantee real-time prices. Catch-up bars still run chronologically and never expose later prices to the policy. Hypothetical next-open fills do not claim to account for wall-clock model latency or executable liquidity.

The watcher waits before open, ignores duplicate bars, retries transient data errors up to `max_data_errors`, and stops when the session is complete or the close-plus-delay-plus-grace deadline is exceeded. `progress.json` exposes the latest consumed bar. A failed/interrupted run reports partial observations and open positions; it does not invent a closing liquidation. Start a new run after an interruption; durable restart/resume is not implemented.

## Automatic reports

Every processed session gets its own report folder; the run root aggregates all sessions:

- `report.html` / `report.md`: executive assessment, costs, benchmark comparison and methodology.
- `performance.png`: equity against the cost-free intraday benchmark and observed drawdown.
- `executions.png`: normalized price paths with simulated buy/sell markers.
- `daily_pnl.png`: net session P&L.
- `report.json`: configuration, exact consumed OHLCV, portfolio snapshots, decisions, fills, source retrieval metadata and errors.
- `equity.csv`, `fills.csv`, `decisions.json`: portable audit ledgers.

Daily Sharpe uses a zero risk-free rate and 252 sessions/year. It is unavailable for fewer than two completed sessions or zero return variance. Win rate counts sell fills, including partial exits. The benchmark is a cost-free equal-weight intraday portfolio, not a claim about achievable returns. Synthetic charts identify their source directly. Reports summarize simulated evidence; they do not generate investment recommendations.

## Extend the framework

Implement the `Policy` protocol and inject a factory; strategies cannot place orders directly:

```python
from trading_agent.config import AgentConfig
from trading_agent.runner import run_backtest
from trading_agent.strategies import Decision

class MyPolicy:
    name = "my_observed_bar_policy"

    def decide(self, observation):
        # observation.history contains only completed bars, copied from host state.
        return Decision(
            weights={symbol: 0.2 for symbol in observation.history},
            reason="Small fixed allocation for a controlled experiment",
        )

run_backtest(
    AgentConfig(symbols=["SPY", "AAPL"]),
    "2026-10-14", "2026-10-14", "artifacts/trading/custom-example",
    policy_factory=MyPolicy,
)
```

A custom `DataFeed.fetch(symbols, start, end, interval)` can return `MarketData` with timezone-aware OHLCV frames, source and retrieval metadata. Keep `start`/`end` inclusive. Host risk limits, cash accounting and chronological execution still apply.

## Verification

```bash
.venv/bin/python -m unittest discover -s trading_agent/tests -v
.venv/bin/python -m compileall -q trading_agent
npm test
npm run build
```

Python tests cover next-bar execution, lack of future-bar access, costs/P&L reconciliation, risk and policy halts, calendar boundaries, data gaps, polling deduplication, transient outages, source attribution and generated artifacts. Network/model calls are mocked; use the CLI for live Yahoo/Ollama verification.
