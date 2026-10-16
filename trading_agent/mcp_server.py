"""Thin MCP facade over the independently supervised execution runtime."""
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from .runtime import JobRequest, runtime_token
from .config import AgentConfig
from .research import DatasetRequest, ExperimentSpec
from .daily_research import DailyResearchSpec
from .sector_research import SectorResearchSpec
from .weekly_research import WeeklyResearchSpec

mcp = MCPServer("assistant-trading", version="1.0.0")


def request_runtime(path, body=None):
    port = int(os.environ.get("TRADING_RUNTIME_PORT", "2612"))
    request = Request(f"http://127.0.0.1:{port}/{path}", data=json.dumps(body).encode() if body is not None else None,
                      headers={"Authorization": f"Bearer {runtime_token()}", "Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=10) as response:
            return json.load(response)
    except HTTPError as error:
        try:
            detail = json.load(error).get("error", str(error))
        except ValueError:
            detail = str(error)
        raise ToolError(detail) from error
    except (URLError, TimeoutError) as error:
        raise ToolError("Trading runtime is offline. Start it with npm run trading:runtime, or install the persistent service.") from error


@mcp.tool()
def trading_start(mode: str = "demo", config: AgentConfig | None = None, start: str | None = None, end: str | None = None,
                  sessions: int = 1, continuous: bool = False) -> dict:
    """Start a background SIMULATION, never broker orders. mode demo (synthetic), backtest (Yahoo completed dates), or watch (delayed Yahoo sessions). config follows AgentConfig: symbols, interval, initial_cash, strategy.kind (sma/momentum/buy_and_hold/ollama), risk, costs. Yahoo 1m history within approximately the last 30 days is automatically fetched in 7-day batches; 2–30m use recent 60 days; 60m uses approximately 730 days. Unsupported historical ranges are rejected before a worker starts; ask before changing requested dates or interval. continuous is watch-only. Returns job ID immediately. Only start when requested by the user; preserve explicit choices, ask for missing tickers for Yahoo modes."""
    try:
        job = JobRequest.model_validate({"mode": mode, "config": config or {}, "start": start, "end": end, "sessions": sessions, "continuous": continuous})
    except ValueError as error:
        raise ToolError(str(error)) from error
    return request_runtime("jobs", job.model_dump())


@mcp.tool()
def trading_status(job_id: str) -> dict:
    """Read a simulation's live equity, holdings, recent decisions/fills and completed report. Requires the exact ID returned by trading_start/list. Data updates on completed delayed bars."""
    _id(job_id)
    return request_runtime(f"jobs/{job_id}")


@mcp.tool()
def trading_list() -> dict:
    """List the latest 50 persistent simulation jobs, including errors and dashboard links."""
    return request_runtime("jobs")


@mcp.tool()
def trading_stop(job_id: str) -> dict:
    """Request graceful cancellation of a user-selected simulation. Partial reports retain actual simulated positions; stopping does not invent closing fills."""
    _id(job_id)
    return request_runtime(f"jobs/{job_id}/stop", {})


@mcp.tool()
def trading_strategies() -> dict:
    """Discover versioned simulated strategies, economic hypotheses, parameter schemas, warm-up requirements and limitations."""
    return request_runtime("strategies")


@mcp.tool()
def trading_validate_strategy(strategy: dict) -> dict:
    """Validate an explicit strategy configuration without starting a simulation. Unknown fields and unsupported versions are rejected."""
    return request_runtime("strategies/validate", strategy)


@mcp.tool()
def trading_dataset_create(dataset: DatasetRequest) -> dict:
    """Create an immutable aggregated-bar dataset in a background job. Preserve requested symbols, dates and interval. Synthetic data is labelled; Yahoo availability is restricted. Return the job ID immediately; use trading_status to obtain the dataset ID and quality/provenance references."""
    return request_runtime("datasets", dataset.model_dump())


@mcp.tool()
def trading_dataset_inspect(dataset_id: str) -> dict:
    """Inspect a saved dataset's immutable manifest, checksum, original request, adjustment settings, provenance and data-quality limitations."""
    _dataset_id(dataset_id)
    return request_runtime(f"datasets/{dataset_id}")


@mcp.tool()
def trading_datasets(limit: int = 20) -> dict:
    """List up to 50 immutable research datasets and their quality summaries."""
    _limit(limit)
    return request_runtime(f"datasets?limit={limit}")


@mcp.tool()
def trading_experiment_start(experiment: ExperimentSpec) -> dict:
    """Start a user-requested bounded simulated walk-forward experiment on one saved dataset, shared capital/risk/cost constraints and explicit chronological periods. Every candidate attempt is recorded. finalize=true explicitly consumes the reserved final test; preserve the user's chosen periods and parameters. Returns a durable experiment/job ID immediately."""
    return request_runtime("experiments", experiment.model_dump())


@mcp.tool()
def trading_experiment_status(job_id: str) -> dict:
    """Inspect bounded experiment progress, attempted configurations, assessments, provenance and artifact references. Use the exact ID returned by experiment start or list."""
    _id(job_id)
    return request_runtime(f"experiments/{job_id}")


@mcp.tool()
def trading_daily_research_start(research: DailyResearchSpec) -> dict:
    """Start one user-requested bounded daily ETF research study on immutable Yahoo observations. Daily adjusted bars are total-return proxies, not trade/quote data or executable fill evidence. Test registered trend hypotheses against matched benchmarks and declared costs; preserve the reserved final dates. Returns a durable job/experiment ID immediately. This is simulated exploratory research, not a validated strategy or profitable-edge claim. Missing history fails explicitly; do not change requested symbols or dates."""
    return request_runtime("daily-research", research.model_dump())


@mcp.tool()
def trading_daily_research_status(job_id: str) -> dict:
    """Inspect one daily research job's bounded progress, assessment, promotion status, provenance and daily-study artifact. Use its exact returned job ID. Cancel through trading_stop; closing MCP does not stop research. A completed exploratory study does not validate a tradable edge."""
    _id(job_id)
    return request_runtime(f"daily-research/{job_id}")


@mcp.tool()
def trading_sector_research_start(research: SectorResearchSpec) -> dict:
    """Start one user-requested frozen sector ETF momentum study: exactly four configurations, fixed universe and 2001–2022 training/validation dates. Yahoo daily adjusted bars are total-return proxies, not executable fills. Preserve the reserved 2023–2025 prices without acquiring or evaluating them. Returns a durable job/experiment ID immediately. Exploratory simulation only, not a validated strategy or profitable-edge claim. Missing history fails explicitly; do not alter the frozen hypothesis."""
    return request_runtime("sector-research", research.model_dump())


@mcp.tool()
def trading_sector_research_status(job_id: str) -> dict:
    """Inspect a sector research job's bounded progress, evidence assessment, provenance and daily-study artifact using its exact returned job ID. Cancel through trading_stop; disconnecting MCP does not stop the independent worker. Completion does not establish a tradable edge."""
    _id(job_id)
    return request_runtime(f"sector-research/{job_id}")


@mcp.tool()
def trading_weekly_research_start(research: WeeklyResearchSpec) -> dict:
    """Start one user-requested frozen global ETF reversal study: exactly four configurations, fixed nine-fund universe and 2008–2022 development/validation dates. Completed weekly targets execute at the next session open; Yahoo adjusted bars remain total-return proxies, not executable fills. Preserve reserved 2023–2025 prices without acquiring or evaluating them. Returns a durable job/experiment ID immediately. Exploratory simulation only, not a validated strategy or profitable-edge claim. Missing history fails explicitly; never alter the frozen hypothesis."""
    return request_runtime("weekly-research", research.model_dump())


@mcp.tool()
def trading_weekly_research_status(job_id: str) -> dict:
    """Inspect one weekly reversal research job's bounded progress, assessment, provenance and daily-study artifact using its exact returned job ID. Cancel through trading_stop; disconnecting MCP does not stop the independent worker. Completion does not establish a tradable edge."""
    _id(job_id)
    return request_runtime(f"weekly-research/{job_id}")


@mcp.tool()
def trading_experiment_attempt(experiment_id: str, attempt_id: str) -> dict:
    """Inspect one saved experiment attempt's bounded decisions, fills, equity and independent reconciliation. Full immutable ledgers remain artifact references; missing or cross-experiment attempt IDs are rejected."""
    _id(experiment_id)
    import re
    if not re.fullmatch(re.escape(experiment_id) + r"-\d{4}", attempt_id):
        raise ToolError("Use an exact attempt ID belonging to this experiment")
    return request_runtime(f"experiments/{experiment_id}/attempts/{attempt_id}")


@mcp.tool()
def trading_experiment_list(limit: int = 20) -> dict:
    """List up to 50 saved experiments plus recent durable experiment job states, including interruptions and failures."""
    _limit(limit)
    return request_runtime(f"experiments?limit={limit}")


@mcp.tool()
def trading_experiment_compare(experiment_ids: list[str]) -> dict:
    """Compare two to six distinct experiments only when dataset, capital/risk/cost and validation periods match. Incomparable experiments are rejected explicitly."""
    if not 2 <= len(experiment_ids) <= 6 or len(set(experiment_ids)) != len(experiment_ids):
        raise ToolError("Compare between two and six distinct experiment IDs")
    for job_id in experiment_ids:
        _id(job_id)
    return request_runtime("experiments/compare", {"experiment_ids": experiment_ids})


@mcp.tool()
def trading_experiment_cancel(job_id: str) -> dict:
    """Gracefully cancel one user-selected research experiment, preserving attempted configurations and partial evidence. Cancellation does not resume or fabricate observations."""
    _id(job_id)
    return request_runtime(f"experiments/{job_id}/stop", {})


def _id(value):
    import re
    if not re.fullmatch(r"[a-f0-9]{32}", value):
        raise ToolError("Use an exact trading job ID")


def _dataset_id(value):
    import re
    if not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ToolError("Use an exact immutable dataset ID")


def _limit(value):
    if not 1 <= value <= 50:
        raise ToolError("limit must be between 1 and 50")


if __name__ == "__main__":
    mcp.run(transport="stdio")
