import { useEffect, useState } from "react";

const money = (value) => Number.isFinite(value) ? new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(value) : "Unavailable";
const time = (value) => value ? new Date(value).toLocaleString() : "Awaiting data";
const active = (status) => ["running", "stopping"].includes(status);

async function request(path, body) {
    const response = await fetch(path, body === undefined ? { cache: "no-store" } : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || result.error || "Trading request failed");
    return result;
}

function EquityChart({ rows }) {
    if (!rows?.length) return <div className="trading-chart-empty">Waiting for the first completed market bar.</div>;
    const values = rows.map((row) => row.equity), min = Math.min(...values), max = Math.max(...values), span = max - min || 1;
    const points = values.map((value, index) => `${65 + index / Math.max(1, values.length - 1) * 710},${195 - (value - min) / span * 155}`).join(" ");
    return <figure className="trading-chart"><svg viewBox="0 0 800 250" role="img" aria-label={`Simulated equity from ${money(values[0])} to ${money(values.at(-1))}`}>
        <line x1="65" x2="775" y1="195" y2="195" stroke="var(--border)" />
        <text x="0" y="48">{money(max)}</text><text x="0" y="190">{money(min)}</text>
        <polyline points={points} fill="none" stroke="var(--accent)" strokeWidth="2.5" />
        <text x="65" y="230">{new Date(rows[0].timestamp).toLocaleTimeString()}</text>
        <text x="775" y="230" textAnchor="end">{new Date(rows.at(-1).timestamp).toLocaleTimeString()}</text>
    </svg><figcaption>Simulated equity, net of modeled costs · times shown in your browser timezone</figcaption></figure>;
}

export default function TradingDashboard({ initialJob = "", pollMs = 3000 }) {
    const [jobs, setJobs] = useState([]), [selected, setSelected] = useState(initialJob), [job, setJob] = useState(null);
    const [mode, setMode] = useState("demo"), [symbols, setSymbols] = useState("SPY, AAPL"), [strategy, setStrategy] = useState("sma");
    const [cash, setCash] = useState("100000"), [interval, setIntervalValue] = useState("5m"), [continuous, setContinuous] = useState(false);
    const [start, setStart] = useState(""), [end, setEnd] = useState("");
    const [error, setError] = useState(""), [busy, setBusy] = useState(false), [connected, setConnected] = useState(false);
    const [connectionError, setConnectionError] = useState("");

    useEffect(() => {
        let cancelled = false, timer;
        async function poll() {
            try {
                const listing = await request("/trading/jobs");
                const id = selected || listing.jobs[0]?.id;
                const detail = id ? await request(`/trading/jobs/${id}`) : null;
                if (cancelled) return;
                setJobs(listing.jobs); setJob(detail); setConnected(true); setConnectionError("");
                if (!selected && id) setSelected(id);
            } catch (failure) {
                if (!cancelled) { setConnectionError(failure.message); setConnected(false); }
            } finally {
                if (!cancelled) timer = setTimeout(poll, pollMs);
            }
        }
        poll();
        return () => { cancelled = true; clearTimeout(timer); };
    }, [selected, pollMs]);

    async function launch(event) {
        event.preventDefault();
        if (busy) return;
        setBusy(true); setError("");
        try {
            const created = await request("/trading/jobs", {
                mode, config: { symbols: symbols.split(",").map((symbol) => symbol.trim().toUpperCase()).filter(Boolean), initial_cash: Number(cash), interval, strategy: { kind: strategy } },
                ...(mode === "backtest" && start ? { start, ...(end ? { end } : {}) } : {}),
                continuous: mode === "watch" && continuous,
            });
            setJob(created); setSelected(created.id);
            setJobs((current) => [created, ...current.filter((item) => item.id !== created.id)]);
            window.history.replaceState(null, "", `?trading_job=${created.id}`);
        } catch (failure) { setError(failure.message); }
        finally { setBusy(false); }
    }

    async function stop() {
        setBusy(true); setError("");
        try { setJob(await request(`/trading/jobs/${selected}/stop`, {})); }
        catch (failure) { setError(failure.message); }
        finally { setBusy(false); }
    }

    const progress = job?.progress, metrics = job?.report?.metrics;
    const latest = progress?.equity?.at(-1);
    const equity = latest?.equity ?? metrics?.final_equity;
    return <section className="trading-dashboard" aria-label="Trading simulations">
        <div className="trading-heading"><div><span className="eyebrow">AUTONOMOUS SIMULATION</span><h2>Trading desk</h2><p>Watch the policy, portfolio, and evidence update as market bars arrive.</p></div><span className={`status-pill ${connected ? "" : "offline"}`}>{connected ? "Runtime connected" : "Runtime offline"}</span></div>
        <p className="trading-notice">Simulation only · USD instruments · Yahoo data may be delayed. The runtime can stay online around the clock; market observations follow NYSE sessions, holidays, and early closes.</p>
        {error && <p className="error" role="alert">{error}</p>}
        {connectionError && <p className="error" role="alert">{connectionError}</p>}
        <div className="trading-layout"><aside className="trading-controls">
            <form onSubmit={launch}>
                <h3>New simulation</h3>
                <label>Run mode<select value={mode} onChange={(event) => setMode(event.target.value)}><option value="demo">Synthetic demo</option><option value="backtest">Historical Yahoo replay</option><option value="watch">Watch Yahoo sessions</option></select></label>
                <label>Yahoo tickers<input value={symbols} required onChange={(event) => setSymbols(event.target.value)} /></label>
                <label>Policy<select value={strategy} onChange={(event) => setStrategy(event.target.value)}><option value="sma">Moving average</option><option value="momentum">Momentum</option><option value="buy_and_hold">Buy and hold</option><option value="ollama">Local Ollama</option></select></label>
                <label>Starting cash (USD)<input type="number" min="1" max="1000000000000" required value={cash} onChange={(event) => setCash(event.target.value)} /></label>
                <label>Bar interval<select value={interval} onChange={(event) => setIntervalValue(event.target.value)}>{["1m", "2m", "5m", "15m", "30m", "60m"].map((value) => <option key={value}>{value}</option>)}</select></label>
                {mode === "backtest" && <><label>Start date (optional)<input type="date" value={start} onChange={(event) => setStart(event.target.value)} /></label><label>End date (optional)<input type="date" value={end} min={start} onChange={(event) => setEnd(event.target.value)} disabled={!start} /></label><small>Defaults to the latest completed session. {interval === "1m" ? "Yahoo 1-minute: automatically fetched in 7-day batches, within approximately the last 30 days." : interval === "60m" ? "Yahoo hourly: approximately the last 730 days." : "Yahoo 2–30-minute: approximately the last 60 days."} Unavailable history is rejected; dates and intervals stay as requested.</small></>}
                {mode === "watch" && <label className="trading-checkbox"><input type="checkbox" checked={continuous} onChange={(event) => setContinuous(event.target.checked)} />Continue across future sessions</label>}
                <button className="primary-btn" disabled={busy}>Start simulation</button>
            </form>
            <h3>Saved jobs</h3>
            {!jobs.length && <p className="meta">No jobs yet.</p>}
            <div className="trading-job-list">{jobs.map((item) => <button key={item.id} type="button" aria-pressed={selected === item.id} onClick={() => { setSelected(item.id); setJob(null); window.history.replaceState(null, "", `?trading_job=${item.id}`); }}><strong>{item.request?.config?.symbols?.join(", ") || "Simulation"}</strong><span>{item.request?.mode} · {item.status}</span><small>{item.id.slice(0, 8)} · {time(item.created_at)}</small>{item.error && <small className="error">{item.error}</small>}</button>)}</div>
        </aside><div className="trading-results">
            {!job ? <div className="trading-empty"><h3>Your portfolio in motion</h3><p>Start a synthetic demo to explore the dashboard without a data provider or model.</p><p>Jobs continue when you close this page. Reopen this tab to inspect their saved state.</p></div> : <>
                <div className="trading-heading"><div><h3>{job.request.config.symbols.join(" / ")}</h3><p><code>{job.id}</code> · {job.status} · {job.request.continuous ? "continuous" : job.request.mode}</p></div>{active(job.status) && <button className="ghost-btn" type="button" disabled={busy || job.status === "stopping"} onClick={stop}>Stop simulation</button>}</div>
                <p className="meta">{job.request.config.interval} bars · Starting cash {money(job.request.config.initial_cash)} · {job.request.start || "Latest completed / upcoming session"}{job.request.end ? ` → ${job.request.end}` : ""}</p>
                {job.error && <p className="error" role="alert">{job.error}</p>}
                <div className="trading-metrics"><div><small>Marked equity</small><strong>{money(equity)}</strong></div><div><small>Cash</small><strong>{money(progress?.cash)}</strong></div><div><small>Observed bars (session)</small><strong>{progress?.completed_bars ?? 0}</strong></div><div><small>Last valuation</small><strong className="trading-timestamp">{time(progress?.valuation_timestamp)}</strong></div></div>
                <p className="meta">{progress?.source || job.report?.source || "Waiting for source data"} · {progress?.state || job.status}{progress?.session ? ` · Session ${progress.session} (New York)` : ""}</p>
                {!connected && <p className="trading-notice">Connection lost. Values below are the last received snapshot.</p>}
                <EquityChart rows={progress?.equity} />
                <h3>Positions</h3><div className="trading-table"><table><thead><tr><th>Symbol</th><th>Shares</th><th>Mark (USD)</th><th>Value (USD)</th></tr></thead><tbody>{Object.entries(progress?.holdings || {}).map(([symbol, position]) => <tr key={symbol}><td>{symbol}</td><td>{position.quantity}</td><td>{money(position.market_price)}</td><td>{money(position.market_value)}</td></tr>)}</tbody></table></div>
                <h3>Recent simulated fills</h3>{!progress?.fills?.length ? <p className="meta">No fills observed.</p> : <div className="trading-table"><table><thead><tr><th>Time</th><th>Symbol</th><th>Side</th><th>Shares</th><th>Price (USD)</th></tr></thead><tbody>{[...progress.fills].reverse().map((fill, index) => <tr key={index}><td>{time(fill.timestamp)}</td><td>{fill.symbol}</td><td>{fill.side}</td><td>{fill.quantity}</td><td>{money(fill.fill_price)}</td></tr>)}</tbody></table></div>}
                <h3>Policy decisions</h3><ul className="trading-decisions">{[...(progress?.decisions || [])].reverse().map((decision, index) => <li key={index}><small>{time(decision.timestamp)}</small><p>{decision.error || decision.reason}</p></li>)}</ul>
                {!!job.artifacts?.length && <div className="trading-artifacts"><h3>Reports &amp; exports</h3>{job.artifacts.map((name) => <a key={name} href={`/trading/jobs/${job.id}/artifacts/${name}`} target="_blank" rel="noreferrer">{name}</a>)}{job.report && <p className="meta">Report: {job.report.status} · generated {time(job.report.generated_at)}. During continuous watch, this report covers completed sessions; the chart shows the current session.</p>}</div>}
            </>}
        </div></div>
    </section>;
}
