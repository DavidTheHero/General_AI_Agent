# Intraday Trading Agent

A modular Python framework for autonomous **paper simulations** over NYSE sessions. It ingests Yahoo Finance OHLCV, runs configurable rule or local AI policies, accounts for positions and execution costs, and writes executive reports and analytical charts automatically. It supports direct CLI execution and integration with the Node chat agent and React trading dashboard through a dedicated MCP server and independent runtime.

## Install and run

From the repository root, using Python 3.11+:

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
| `strategies.py` | SMA, momentum, buy-and-hold and structured Ollama allocation policies. |
| `portfolio.py` | Cash, whole-share inventory, average cost, fills, fees and realized P&L. |
| `engine.py` | Autonomous per-bar loop, next-open execution, risk stops and immutable history. |
| `metrics.py` | Portfolio/benchmark returns, drawdown, costs, exposure, turnover, realized/unrealized P&L and daily statistics. |
| `runner.py` | Multi-session replay and near-real-time polling with automatic reports. |
| `reporting.py` | Deterministic evidence-based executive narratives, PNG charts and audit ledgers. |
| `cli.py` | Runnable jobs and output-directory management. |
| `runtime.py` | Token-protected loopback job service, durable SQLite registry, worker lifecycle and artifact access. |
| `mcp_server.py` | Four thin MCP tools for starting, inspecting, listing and stopping runtime jobs. |

## Integrated execution

Install MCP support with `.venv/bin/python -m pip install -e '.[mcp]'`, then run `npm run trading:runtime` alongside `npm run dev`. Open **Trading desk** or ask chat to run a synthetic demo. For continuous operation and process supervision, see [deploy/README.md](../deploy/README.md).

The MCP server is a control plane over local HTTP; the runtime owns worker processes and writes job status independently of chat or browser connections. Each tool call returns quickly without waiting for a trading session. Dashboard polling reads atomic bar snapshots containing observed equity, holdings, recent decisions and fills. Completed reports remain available through an explicit artifact allowlist. Jobs and reports persist on disk. This is an application-level job API, not an implementation of the optional MCP Tasks protocol.

Normal cancellation requests a partial report without inventing liquidation. If the runtime dies, workers detect the closed parent pipe and exit; on restart unfinished registry entries become **interrupted**. Inspect their saved evidence and explicitly create a new run. Jobs are not silently resumed, and the service supervisor restarts the service rather than recreating portfolio state. Yahoo failure limits and policy-error halts still stop continuous runs. Keep the machine awake, connected, and Ollama running for AI policies.

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
