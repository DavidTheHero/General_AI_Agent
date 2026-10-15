"""Thin MCP facade over the independently supervised execution runtime."""
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from .runtime import JobRequest, runtime_token
from .config import AgentConfig

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


def _id(value):
    import re
    if not re.fullmatch(r"[a-f0-9]{32}", value):
        raise ToolError("Use an exact trading job ID")


if __name__ == "__main__":
    mcp.run(transport="stdio")
