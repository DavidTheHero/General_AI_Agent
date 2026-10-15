import { useState } from "react";
import FinanceReport from "./FinanceReport.jsx";

export const workflows = [
    ["research", "Company research"], ["comparison", "Compare companies"], ["earnings", "Earnings explorer"],
    ["overlap", "ETF overlap"], ["screener", "Stock screener"], ["portfolio", "Portfolio & FX"], ["morning", "Market brief"],
];
const parseSymbols = (text) => text.split(/[,\s]+/).filter(Boolean).map((symbol) => symbol.toUpperCase());
const localDate = () => new Intl.DateTimeFormat("en-CA").format(new Date());

export default function FinanceWorkspace({ onChat }) {
    const [workflow, setWorkflow] = useState("research");
    const [symbol, setSymbol] = useState("NVDA");
    const [symbolList, setSymbolList] = useState("NVDA, AMD, INTC");
    const [funds, setFunds] = useState("SPY, QQQ");
    const [period, setPeriod] = useState("3mo");
    const [sector, setSector] = useState("Technology");
    const [maxPe, setMaxPe] = useState(30), [maxDebt, setMaxDebt] = useState(100);
    const [currency, setCurrency] = useState("GBP");
    const [positions, setPositions] = useState("NVDA, 10\nMSFT, 5");
    const [date, setDate] = useState(localDate), [watchlist, setWatchlist] = useState("NVDA, MSFT");
    const [report, setReport] = useState(null), [busy, setBusy] = useState(false), [error, setError] = useState("");

    function buildRequest() {
        if (workflow === "research" || workflow === "earnings") return { workflow, symbol };
        if (workflow === "comparison") return { workflow, symbols: parseSymbols(symbolList), period };
        if (workflow === "overlap") return { workflow, symbols: parseSymbols(funds) };
        if (workflow === "screener") return { workflow, sector, max_pe: Number(maxPe), max_debt_equity: Number(maxDebt) };
        if (workflow === "portfolio") {
            const rows = positions.split("\n").filter((row) => row.trim()).map((row) => {
                const [ticker, quantity, cost, purchaseDate, ...extra] = row.split(",").map((value) => value.trim());
                if (extra.length) throw new Error("Use SYMBOL, quantity, optional per-share cost basis, optional purchase date.");
                return { symbol: ticker, quantity: Number(quantity), ...(cost ? { cost_basis: Number(cost) } : {}), ...(purchaseDate ? { purchase_date: purchaseDate } : {}) };
            });
            return { workflow, currency, positions: rows };
        }
        return { workflow, date, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone, watchlist: parseSymbols(watchlist) };
    }
    async function run(request) {
        setBusy(true); setError(""); setReport(null);
        try {
            const response = await fetch("/finance/workspace", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(request) });
            const result = await response.json();
            if (!response.ok) throw new Error(result.detail || result.error || "Report request failed.");
            setReport(result);
        } catch (failure) { setError(failure.message); }
        finally { setBusy(false); }
    }
    function submit(event) {
        event.preventDefault();
        if (busy) return;
        try { run(buildRequest()); } catch (failure) { setError(failure.message); }
    }
    return <section className="workspace" aria-label="Finance workspace">
        <div className="workspace-intro"><span className="eyebrow">MARKET RESEARCH</span><h1>Finance workspace</h1><p>From a question to a clearer picture. Explore the data behind every decision.</p></div>
        <nav className="workspace-tabs" aria-label="Finance workflows">{workflows.map(([key, label]) => <button type="button" key={key} aria-pressed={workflow === key} disabled={busy} onClick={() => { setWorkflow(key); setReport(null); setError(""); }}><span className="workflow-number" aria-hidden="true">{String(workflows.findIndex(([item]) => item === key) + 1).padStart(2, "0")}</span>{label}<span className="workflow-arrow" aria-hidden="true">↗</span></button>)}</nav>
        <div className="workspace-content"><div className="workflow-heading"><span className="eyebrow">RESEARCH TOOL</span><h2>{workflows.find(([key]) => key === workflow)?.[1]}</h2><p>Set your inputs below. Every report includes its underlying sources.</p></div>
        <form className="workspace-form" onSubmit={submit}>
            {(workflow === "research" || workflow === "earnings") && <label>Stock ticker<input value={symbol} onChange={(event) => setSymbol(event.target.value)} required placeholder="NVDA" /></label>}
            {workflow === "comparison" && <><label>Company tickers (2–4)<input value={symbolList} onChange={(event) => setSymbolList(event.target.value)} required /></label><label>Price period<select value={period} onChange={(event) => setPeriod(event.target.value)}>{["1mo", "3mo", "6mo", "1y"].map((item) => <option key={item}>{item}</option>)}</select></label></>}
            {workflow === "overlap" && <label>Two ETF tickers<input value={funds} onChange={(event) => setFunds(event.target.value)} required /></label>}
            {workflow === "screener" && <><label>Sector<select value={sector} onChange={(event) => setSector(event.target.value)}>{["Technology", "Healthcare", "Financial Services", "Industrials", "Consumer Cyclical"].map((item) => <option key={item}>{item}</option>)}</select></label><label>Maximum trailing P/E<input type="number" min="1" max="200" value={maxPe} onChange={(event) => setMaxPe(event.target.value)} required /></label><label>Maximum debt/equity (%)<input type="number" min="0" max="1000" step="1" value={maxDebt} onChange={(event) => setMaxDebt(event.target.value)} required /></label><p>Positive trailing net income is required. The report shows the exact executed filters.</p></>}
            {workflow === "portfolio" && <><label>Display currency<select value={currency} onChange={(event) => setCurrency(event.target.value)}>{["GBP", "USD", "EUR", "JPY", "CAD", "AUD"].map((item) => <option key={item}>{item}</option>)}</select></label><label className="wide-label">Positions<textarea value={positions} onChange={(event) => setPositions(event.target.value)} required /></label><p>One per line: SYMBOL, quantity, optional per-share cost basis, optional purchase date (YYYY-MM-DD). Supply both cost and date to calculate stock and FX effects. Holdings stay in this form; no broker account is connected.</p></>}
            {workflow === "morning" && <><label>Briefing date<input type="date" value={date} onChange={(event) => setDate(event.target.value)} required /></label><label>Watchlist tickers (up to 5)<input value={watchlist} onChange={(event) => setWatchlist(event.target.value)} /></label><p>US benchmarks and latest available daily observations. Generate on demand; no scheduled delivery is configured.</p></>}
            <button className="primary-btn" disabled={busy}>{busy ? "Building report…" : "Generate report"}</button>
        </form>
        {busy && <p role="status">Fetching source data through your finance MCP server. Several datasets may take a minute.</p>}
        {error && <p className="error" role="alert">{error}</p>}
        {!report && !busy && !error && <div className="report-placeholder"><span aria-hidden="true">↗</span><h3>Your next insight starts here</h3><p>Generate a report to explore charts, compare figures, and inspect the source data.</p><small>Yahoo Finance · Daily observations · Source-backed reports</small></div>}
        {report && <FinanceReport report={report} onFollowup={(next) => {
            if (next.query) onChat?.(next.query);
            else { setWorkflow(next.workflow); setSymbol(next.symbol); run(next); }
        }} />}</div>
    </section>;
}
