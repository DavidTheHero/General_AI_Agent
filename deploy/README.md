# Persistent local services

The trading runtime, MCP tools and web app have independent lifetimes:

```text
React dashboard / Node chat agent
           ↓
Node TradingMcpClient → Python trading MCP (stdio)
                              ↓ short local HTTP calls
                   Persistent Python runtime (2612)
                              ↓ background worker processes
                   Yahoo feed → policy → portfolio → reports
```

MCP tools return job IDs; workers continue after the browser or MCP connection closes. This separation fits [MCP's stdio process lifecycle](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/basic/transports/stdio.mdx): closing a stdio client ends its MCP subprocess, so session-length trading work belongs in a separate runtime.

## Development

From the repository root:

```bash
npm ci
.venv/bin/python -m pip install -r backend/finance/requirements.txt
.venv/bin/python -m pip install -e '.[mcp]'
npm run trading:runtime
# In a second terminal:
npm run dev
```

Open http://localhost:2611 and select **Trading desk**. Start with **Synthetic demo**. **Watch Yahoo sessions** polls the active/upcoming NYSE session. Select **Continue across future sessions** for continuous operation; holidays and early closes follow the exchange calendar. The UI polls every three seconds; market data advances at the configured bar interval and source delay.

## macOS launchd

These commands install two user services and start them immediately. Stop manually started runtime/web processes first to free ports 2612/2610. Keep Ollama available separately for chat and AI policies.

```bash
npm run build
.venv/bin/python deploy/install_service.py trading --install
.venv/bin/python deploy/install_service.py web --install
```

Open http://localhost:2610. The services start at login and restart after process exits. They run under the logged-in user, including while terminals are closed. Sleep, logout and network outages still interrupt availability; this is not cloud hosting or an uptime guarantee. Installing services does not automatically start a simulation. Start an explicit continuous watch in the dashboard.

Run the script without `--install` to inspect the generated plist. Logs are under `artifacts/trading/services/`. To stop and remove services while keeping saved jobs:

```bash
.venv/bin/python deploy/install_service.py web --uninstall
.venv/bin/python deploy/install_service.py trading --uninstall
```

For Linux, supervise `.venv/bin/python -m trading_agent.runtime` and `node --env-file-if-exists=.env backend/server.js` with your existing process supervisor, using this repository as the working directory and the same local user. The runtime currently requires POSIX file locking.

## Persistence and operation

- Default data directory: `artifacts/trading/runtime/`, containing `jobs.sqlite`, a private generated `token`, and job-specific logs, configuration and report folders. Keep it out of version control.
- `TRADING_RUNTIME_PORT` and `TRADING_DATA_DIR` must match across runtime, MCP and Node. npm commands load `.env`; the launchd **web** service loads `.env`. For custom trading-service values, export those two variables before installing its plist; they are captured at installation.
- `GET/POST /trading/jobs`, `GET /trading/jobs/:id`, and `POST /trading/jobs/:id/stop` are the Node UI endpoints. The separate runtime requires its generated bearer token; React never receives that token.
- At most two simulations run at once. Jobs survive UI/Node/MCP restarts while the runtime stays alive. Recent 50 jobs appear in the dashboard; artifacts are retained until manually removed.
- Runtime shutdown cancels its workers. Unexpected runtime loss ends workers through a parent-lifetime pipe. On restart unfinished jobs are labeled **interrupted**, with their last saved marks and positions. No automatic intraday recovery or invented closing fills.
- A continuous job remains active across sessions until stopped, a provider/execution failure, capital exhaustion, or a policy-error halt. Completed-session reports aggregate its history; the live equity chart shows the current session.
- All endpoints bind locally and assume a single trusted user. Add authentication and deployment hardening before exposing them beyond localhost. This implementation simulates trades and has no broker connection.
