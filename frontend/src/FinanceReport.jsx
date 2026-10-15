import { useState } from "react";

export function formatNumber(value, currency = null) {
    if (typeof value !== "number" || !Number.isFinite(value)) return "Unavailable";
    if (currency && /^[A-Z]{3}$/.test(currency)) {
        try { return new Intl.NumberFormat("en-GB", { style: "currency", currency, maximumFractionDigits: 2, notation: Math.abs(value) >= 1000000 ? "compact" : "standard" }).format(value); } catch { /* Preserve unknown units below. */ }
    }
    return new Intl.NumberFormat("en-GB", { maximumFractionDigits: 2, notation: Math.abs(value) >= 1000000 ? "compact" : "standard" }).format(value) + (currency ? ` ${currency}` : "");
}
const percentage = (value) => typeof value === "number" && Number.isFinite(value) ? `${value.toFixed(2)}%` : "Unavailable";
const link = (url) => {
    try { const parsed = new URL(url); return ["https:", "http:"].includes(parsed.protocol) ? parsed.href : null; } catch { return null; }
};
function SourceLink({ url, children }) {
    const target = link(url);
    return target ? <a href={target} target="_blank" rel="noreferrer">{children}</a> : <span>{children}</span>;
}

export function DataTable({ columns, rows, caption }) {
    return <div className="table-scroll"><table>
        {caption && <caption>{caption}</caption>}
        <thead><tr>{columns.map((column) => <th key={column.key} scope="col">{column.label}</th>)}</tr></thead>
        <tbody>{rows.length ? rows.map((row, index) => <tr key={row.symbol || row.period || index}>{columns.map((column) => <td key={column.key}>{column.render ? column.render(row[column.key], row) : row[column.key] ?? "Unavailable"}</td>)}</tr>) : <tr><td colSpan={columns.length}>No data available.</td></tr>}</tbody>
    </table></div>;
}

export function LineChart({ title, labels, series, currency = null, unit = null }) {
    const [hidden, setHidden] = useState([]);
    const active = series.filter((item) => !hidden.includes(item.name));
    const numbers = active.flatMap((item) => item.values).filter((value) => typeof value === "number" && Number.isFinite(value));
    const lower = Math.min(0, ...numbers), upper = Math.max(0, ...numbers);
    const range = upper - lower || 1;
    const x = (i) => 70 + i * 570 / Math.max(1, labels.length - 1);
    const y = (value) => 175 - (value - lower) / range * 145;
    const colors = ["#60a5fa", "#34d399", "#fbbf24", "#f472b6"];
    return <section className="report-chart" aria-label={title}>
        <h3>{title}{currency ? ` (${currency})` : unit ? ` (${unit})` : ""}</h3>
        <div className="chart-legend">{series.map((item, i) => <button type="button" key={item.name} aria-pressed={!hidden.includes(item.name)} onClick={() => setHidden((items) => items.includes(item.name) ? items.filter((name) => name !== item.name) : [...items, item.name])} style={{ borderColor: colors[i % colors.length] }}>{item.name}</button>)}</div>
        {numbers.length ? <svg viewBox="0 0 680 215" role="img" aria-label={`${title}; numerical values are in the data table below`}>
            {[0, .5, 1].map((step) => <g key={step}><line x1="70" x2="640" y1={30 + step * 145} y2={30 + step * 145} className="chart-grid" /><text x="62" y={34 + step * 145} textAnchor="end">{formatNumber(upper - step * range)}{unit === "%" ? "%" : ""}</text></g>)}
            {series.map((item, i) => {
                if (hidden.includes(item.name)) return null;
                let previous = false;
                const path = item.values.map((value, index) => {
                    if (typeof value !== "number" || !Number.isFinite(value)) { previous = false; return ""; }
                    const segment = `${previous ? "L" : "M"}${x(index)},${y(value)}`; previous = true; return segment;
                }).join(" ");
                return <g key={item.name}><path d={path} fill="none" stroke={colors[i % colors.length]} strokeWidth="2.5" />{item.values.map((value, index) => typeof value === "number" && Number.isFinite(value) ? <circle key={index} cx={x(index)} cy={y(value)} r="3" fill={colors[i % colors.length]}><title>{`${item.name} ${labels[index]}: ${formatNumber(value, currency)}${unit === "%" ? "%" : ""}`}</title></circle> : null)}</g>;
            })}
            {labels.map((label, index) => (labels.length <= 6 || index === 0 || index === labels.length - 1 || index === Math.floor(labels.length / 2)) && <text key={label} x={x(index)} y="202" textAnchor="middle">{label}</text>)}
        </svg> : <p>No chart data available.</p>}
        <details><summary>Chart data</summary><DataTable columns={[{ key: "date", label: "Date" }, ...series.map((item) => ({ key: item.name, label: item.name, render: (value) => unit === "%" ? percentage(value) : formatNumber(value, currency) }))]} rows={labels.map((date, i) => ({ date, ...Object.fromEntries(series.map((item) => [item.name, item.values[i]])) }))} /></details>
    </section>;
}

function Quarterly({ data }) {
    const currency = data.profile.financial_currency;
    return <>
        {!currency && <p className="report-warning">Financial reporting currency is unavailable; raw monetary units are shown.</p>}
        <LineChart title="Quarterly revenue" labels={data.quarters.map(({ period }) => period)} series={[{ name: "Revenue", values: data.quarters.map(({ revenue }) => revenue) }]} currency={currency} />
        <LineChart title="Quarterly cash flow" labels={data.quarters.map(({ period }) => period)} series={[{ name: "Operating cash flow", values: data.quarters.map(({ operating_cashflow }) => operating_cashflow) }, { name: "Free cash flow", values: data.quarters.map(({ free_cashflow }) => free_cashflow) }]} currency={currency} />
        <DataTable caption="Reported quarters" columns={[
            { key: "period", label: "Quarter ending" }, { key: "revenue", label: "Revenue", render: (value) => formatNumber(value, currency) },
            { key: "net_income", label: "Net income", render: (value) => formatNumber(value, currency) },
            { key: "operating_margin", label: "Operating margin", render: percentage },
            { key: "free_cashflow", label: "Free cash flow", render: (value) => formatNumber(value, currency) },
        ]} rows={data.quarters} />
    </>;
}

function ProviderTable({ value }) {
    if (!value) return <p>No data available.</p>;
    if (Array.isArray(value.columns) && Array.isArray(value.rows)) {
        return <DataTable columns={[{ key: "index", label: "Event / period" }, ...value.columns.map((label, i) => ({ key: String(i), label: String(label) }))]} rows={value.rows.map((row, i) => ({ index: value.index?.[i] ?? i, ...Object.fromEntries(row.map((cell, j) => [String(j), typeof cell === "object" && cell !== null ? JSON.stringify(cell) : cell])) }))} />;
    }
    return <pre>{JSON.stringify(value, null, 2)}</pre>;
}

export default function FinanceReport({ report, onFollowup }) {
    const { workflow, data } = report;
    return <article className="finance-report">
        <div className="report-heading"><span className="report-kicker">{workflow.replaceAll("_", " ")} · Yahoo Finance</span><small>Retrieved {new Date(report.generated_at).toLocaleString()}</small></div>
        {(workflow === "research" || workflow === "earnings") && <>
            <h2>{data.profile.name} <span>{data.profile.symbol}</span></h2>
            <p>{[data.profile.sector, data.profile.industry].filter(Boolean).join(" · ")}</p>
            <div className="metric-grid">
                <div><span>Daily price · {data.profile.price_date || "date unavailable"}</span><b>{formatNumber(data.profile.price, data.profile.currency)}</b></div>
                <div><span>Revenue change · QoQ</span><b>{percentage(data.changes.revenue_qoq_pct)}</b></div>
                <div><span>Trailing P/E</span><b>{formatNumber(data.profile.trailing_pe)}</b></div>
                <div><span>Market cap</span><b>{formatNumber(data.profile.market_cap, data.profile.currency === "GBp" || data.profile.currency === "GBX" ? "GBP" : data.profile.currency)}</b></div>
            </div>
            {workflow === "research" && <p>{data.profile.description || "Business description unavailable."}</p>}
            <SourceLink url={data.profile.source_url}>Company source</SourceLink>
            {data.observations.length > 0 && <section><h3>What changed?</h3><ul>{data.observations.map((item) => <li key={item}>{item}</li>)}</ul></section>}
            <Quarterly data={data} />
            {workflow === "research" && <>
                <h3>Valuation snapshot</h3><DataTable columns={[{ key: "metric", label: "Metric" }, { key: "value", label: "Value", render: (value) => formatNumber(value) }]} rows={[["Forward P/E", data.profile.forward_pe], ["Price / book", data.profile.price_to_book], ["Enterprise value / revenue", data.profile.enterprise_to_revenue]].map(([metric, value]) => ({ metric, value }))} />
                <h3>Analyst targets (estimates)</h3><ProviderTable value={data.analyst_targets} />
                <h3>Earnings and company calendar</h3><ProviderTable value={data.calendar} />
                <Headlines items={data.news} />
            </>}
            {onFollowup && <div className="report-followups"><button type="button" onClick={() => onFollowup({ workflow: "earnings", symbol: data.profile.symbol })}>Explore earnings</button><button type="button" onClick={() => onFollowup({ query: `Explain free cash flow for ${data.profile.symbol} using its latest quarterly cash flow statement` })}>Explain cash flow in chat</button></div>}
        </>}
        {workflow === "comparison" && <>
            <h2>Company comparison</h2><p>Common financial quarter: {data.common_period || "Unavailable"}</p>
            <DataTable columns={[
                { key: "symbol", label: "Company", render: (value, row) => <SourceLink url={row.source_url}>{value}</SourceLink> },
                { key: "price", label: "Price", render: (value, row) => formatNumber(value, row.currency) },
                { key: "trailing_pe", label: "Trailing P/E", render: (value) => formatNumber(value) },
                { key: "quarter", label: "Quarterly revenue", render: (value, row) => formatNumber(value?.revenue, row.financial_currency) },
                { key: "quarter_margin", label: "Operating margin", render: (_value, row) => percentage(row.quarter?.operating_margin) },
            ]} rows={data.companies} />
            <LineChart title="Aligned adjusted price performance" labels={data.performance.dates} series={data.performance.series.map(({ symbol, values }) => ({ name: symbol, values }))} unit="%" />
            <DataTable columns={[{ key: "symbol", label: "Company" }, { key: "return_pct", label: "Return over common dates", render: percentage }]} rows={data.performance.series} />
        </>}
        {workflow === "overlap" && <>
            <h2>ETF overlap · {data.funds.map(({ symbol }) => symbol).join(" / ")}</h2>
            <div className="metric-grid"><div><span>Observed overlap (lower bound)</span><b>{percentage(data.overlap_pct)}</b></div>{data.coverage.map((item) => <div key={item.symbol}><span>{item.symbol} returned holdings weight</span><b>{percentage(item.weight_pct)}</b><small>{item.count} holdings</small></div>)}</div>
            <DataTable columns={[{ key: "symbol", label: "Shared holding" }, { key: "name", label: "Name" }, { key: "weight_a", label: data.funds[0].symbol, render: (value) => percentage(value * 100) }, { key: "weight_b", label: data.funds[1].symbol, render: (value) => percentage(value * 100) }, { key: "shared_weight", label: "Minimum shared weight", render: (value) => percentage(value * 100) }]} rows={data.shared} />
        </>}
        {workflow === "screener" && <>
            <h2>Stock screener</h2>
            <p>{data.criteria.sector} · Positive trailing net income · P/E below {data.criteria.max_pe} · Debt/equity at most {data.criteria.max_debt_equity}%</p>
            <DataTable columns={[{ key: "symbol", label: "Symbol", render: (value, row) => <SourceLink url={row.source_url}>{value}</SourceLink> }, { key: "name", label: "Company" }, { key: "price", label: "Price", render: (value, row) => formatNumber(value, row.currency) }, { key: "trailing_pe", label: "P/E", render: (value) => formatNumber(value) }, { key: "explanation", label: "Why returned" }]} rows={data.matches} />
            <details><summary>Executed screening filters</summary><pre>{JSON.stringify(data.filters, null, 2)}</pre></details>
        </>}
        {workflow === "portfolio" && <>
            <h2>Portfolio currency dashboard</h2>
            <div className="metric-grid"><div><span>{data.complete ? "Total value" : "Total unavailable (incomplete prices or FX)"}</span><b>{formatNumber(data.total, data.currency)}</b></div>{!data.complete && <div><span>Available subtotal</span><b>{formatNumber(data.available_subtotal, data.currency)}</b></div>}</div>
            <DataTable columns={[{ key: "symbol", label: "Symbol" }, { key: "quantity", label: "Quantity" }, { key: "price", label: "Native price", render: (value, row) => formatNumber(value, row.native_currency) }, { key: "display_value", label: `Value (${data.currency})`, render: (value) => formatNumber(value, data.currency) }, { key: "quote_date", label: "Stock date" }, { key: "fx_date", label: "FX date" }]} rows={data.positions} />
            <h3>Stock and currency effects</h3><p>Available when per-share cost basis and purchase date were supplied.</p>
            <DataTable columns={[{ key: "symbol", label: "Symbol" }, ...[["stock_effect", "Stock-price effect"], ["fx_effect", "Currency effect"], ["total_change", "Total change"]].map(([key, label]) => ({ key, label, render: (_value, row) => formatNumber(row.attribution?.[key], data.currency) }))]} rows={data.positions} />
        </>}
        {workflow === "morning" && <>
            <h2>Market brief · {data.date}</h2><p>US benchmarks · Briefing timezone: {data.timezone}</p>
            <DataTable columns={[{ key: "symbol", label: "Benchmark / watchlist" }, { key: "quote", label: "Latest daily value", render: (value, row) => row.symbol.startsWith("^") ? `${formatNumber(value?.price)} points` : formatNumber(value?.price, value?.currency) }, { key: "change", label: "Daily change", render: (_value, row) => percentage(row.quote?.percent_change) }, { key: "date", label: "Observation date", render: (_value, row) => row.quote?.date || "Unavailable" }]} rows={[...data.benchmarks, ...data.watchlist]} />
            <h3>Earnings calendar</h3><ProviderTable value={data.earnings} /><h3>Economic events</h3><ProviderTable value={data.economic} /><Headlines items={data.news} />
        </>}
        <p className="report-basis">{data.basis}</p>
        {report.warnings.length > 0 && <section className="report-warning" aria-label="Data availability"><h3>Data availability</h3><ul>{report.warnings.map((warning, i) => <li key={i}>{warning.section}: {warning.message}</li>)}</ul></section>}
        <details className="report-sources"><summary>Sources and underlying data ({report.sources.length})</summary>{report.sources.map((source, i) => <details key={i}><summary>{source.section} · {source.source} · {source.retrieved_at}</summary><pre>{JSON.stringify(source.data, null, 2)}</pre></details>)}</details>
    </article>;
}
function Headlines({ items = [] }) {
    return <section><h3>Recent headlines</h3>{items.length ? <ul>{items.map((item, i) => <li key={i}><SourceLink url={item.url}>{item.title}</SourceLink><small> {item.provider} {item.published_at}</small></li>)}</ul> : <p>No headlines available.</p>}</section>;
}
