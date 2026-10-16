import { useEffect, useState } from "react";

const defaults = ["trend_following", "mean_reversion", "opening_range_breakout"].map((kind) => ({ kind, version: "1.0.0" }));
const money = (value) => Number.isFinite(value) ? new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(value) : "Unavailable";
const percent = (value) => Number.isFinite(value) ? `${value.toFixed(2)}%` : "Unavailable";
const identifier = (item) => item.experiment_id || item.dataset_id || item.id;
const inProgress = (status) => ["pending", "running", "stopping"].includes(status);
const display = (value) => typeof value === "string" ? value : JSON.stringify(value, null, 2);

async function request(path, body) {
    const response = await fetch(path, body === undefined ? { cache: "no-store" } : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || result.error || "Research request failed");
    return result;
}

function Metrics({ metrics = {} }) {
    return <><td>{percent(metrics.return_pct)}</td><td>{percent(metrics.benchmark_return_pct)}</td><td>{percent(metrics.max_drawdown_pct)}</td><td>{money(metrics.commission_cost)}</td><td>{money(metrics.slippage_cost)}</td></>;
}

function AttemptChart({ session }) {
    const rows = (session.equity || []).filter((row) => Number.isFinite(row.equity));
    if (!rows.length) return <p>No verified equity observations in this snapshot.</p>;
    const values = rows.map((row) => row.equity), minimum = Math.min(...values), maximum = Math.max(...values), span = maximum - minimum || 1;
    let peak = values[0];
    const hasHistoricalPeaks = rows.every((row) => Number.isFinite(row.drawdown));
    const drawdowns = rows.map((row) => { peak = Math.max(peak, row.equity); return Number.isFinite(row.drawdown) ? row.drawdown * 100 : (row.equity / peak - 1) * 100; });
    const worst = Math.min(0, ...drawdowns), drawdownSpan = -worst || 1;
    const x = (index) => 95 + index / Math.max(1, rows.length - 1) * 680;
    const equityPoints = values.map((value, index) => `${x(index)},${160 - (value - minimum) / span * 120}`).join(" ");
    const drawdownPoints = drawdowns.map((value, index) => `${x(index)},${205 - value / drawdownSpan * 70}`).join(" ");
    return <figure className="trading-chart"><svg viewBox="0 0 800 315" role="img" aria-label={`Attempt equity and drawdown for session ${session.session}, ${rows.length} displayed observations`}>
        <text x="0" y="40">{money(maximum)}</text><text x="0" y="160">{money(minimum)}</text>
        <polyline points={equityPoints} fill="none" stroke="var(--accent)" strokeWidth="2.5" />
        <line x1="95" x2="775" y1="205" y2="205" stroke="var(--border)" /><text x="0" y="205">0% drawdown</text><text x="0" y="275">{percent(worst)}</text>
        <polyline points={drawdownPoints} fill="none" stroke="#dba86c" strokeWidth="2.5" />
        <text x="95" y="305">{rows[0].timestamp}</text><text x="775" y="305" textAnchor="end">{rows.at(-1).timestamp}</text>
    </svg><figcaption>Simulated equity net of modeled costs and {hasHistoricalPeaks ? "session drawdown" : "drawdown within the displayed window"} · {rows.length} observations shown · UTC timestamps{!hasHistoricalPeaks && ". Earlier peaks outside this snapshot are unavailable."}</figcaption></figure>;
}

export default function ResearchDashboard({ pollMs = 3000, initialExperiment = "" }) {
    const [strategies, setStrategies] = useState([]), [datasets, setDatasets] = useState([]), [experiments, setExperiments] = useState([]);
    const [datasetId, setDatasetId] = useState(""), [dataset, setDataset] = useState(null), [datasetJob, setDatasetJob] = useState(null);
    const [experimentId, setExperimentId] = useState(initialExperiment), [job, setJob] = useState(null), [experiment, setExperiment] = useState(null), [attemptEvidence, setAttemptEvidence] = useState(null);
    const [source, setSource] = useState("synthetic"), [symbols, setSymbols] = useState("SPY"), [start, setStart] = useState("2026-09-01"), [end, setEnd] = useState("2026-09-18"), [interval, setIntervalValue] = useState("5m");
    const [candidates, setCandidates] = useState(JSON.stringify(defaults, null, 2)), [train, setTrain] = useState("2"), [validation, setValidation] = useState("1"), [finalSessions, setFinalSessions] = useState("2");
    const [cash, setCash] = useState("100000"), [commission, setCommission] = useState("1"), [slippage, setSlippage] = useState("2"), [multipliers, setMultipliers] = useState("1, 2");
    const [busy, setBusy] = useState(false), [error, setError] = useState(""), [connectionError, setConnectionError] = useState(""), [notice, setNotice] = useState("");
    const [comparisonIds, setComparisonIds] = useState([]), [comparison, setComparison] = useState(null);

    useEffect(() => {
        let cancelled = false, timer;
        async function poll() {
            try {
                const [registry, listing, studies] = await Promise.all([request("/trading/strategies"), request("/trading/datasets"), request("/trading/experiments")]);
                const saved = [...studies.experiments, ...(studies.jobs || []).filter((item) => !studies.experiments.some((value) => identifier(value) === item.id))];
                const currentDatasetId = datasetId || (listing.datasets[0] && identifier(listing.datasets[0]));
                const currentExperimentId = experimentId || (saved[0] && identifier(saved[0]));
                const [manifest, detail, creation] = await Promise.all([
                    currentDatasetId ? request(`/trading/datasets/${currentDatasetId}`) : null,
                    currentExperimentId ? request(`/trading/experiments/${currentExperimentId}`) : null,
                    datasetJob?.id && inProgress(datasetJob.status) ? request(`/trading/jobs/${datasetJob.id}`) : null,
                ]);
                if (cancelled) return;
                setStrategies(registry.strategies); setDatasets(listing.datasets); setExperiments(saved);
                setDataset(manifest); setJob(detail); setExperiment(detail?.experiment || null); setConnectionError("");
                if (!datasetId && currentDatasetId) setDatasetId(currentDatasetId);
                if (!experimentId && currentExperimentId) setExperimentId(currentExperimentId);
                if (creation) {
                    setDatasetJob(creation);
                    if (creation.report?.dataset_id) setDatasetId(creation.report.dataset_id);
                }
            } catch (failure) { if (!cancelled) setConnectionError(failure.message); }
            finally { if (!cancelled) timer = setTimeout(poll, pollMs); }
        }
        poll();
        return () => { cancelled = true; clearTimeout(timer); };
    }, [datasetId, experimentId, datasetJob?.id, datasetJob?.status, pollMs]);

    async function act(action) {
        if (busy) return;
        setBusy(true); setError(""); setNotice("");
        try { await action(); }
        catch (failure) { setError(failure.message); }
        finally { setBusy(false); }
    }

    function parsedCandidates() {
        const values = JSON.parse(candidates);
        if (!Array.isArray(values) || !values.length) throw new Error("Provide at least one candidate configuration.");
        return values;
    }

    function createDataset(event) {
        event.preventDefault();
        act(async () => {
            const created = await request("/trading/datasets", { source, symbols: symbols.split(",").map((symbol) => symbol.trim().toUpperCase()).filter(Boolean), start, end, interval, ...(source === "synthetic" ? { seed: 17 } : {}) });
            setDatasetJob(created);
            setNotice(`Dataset creation job ${created.id}. Original dates and interval are preserved.`);
        });
    }

    function runExperiment(event) {
        event.preventDefault();
        act(async () => {
            const config = { symbols: dataset.request?.symbols || dataset.symbols, interval: dataset.request?.interval || dataset.interval,
                initial_cash: Number(cash), costs: { commission_bps: Number(commission), slippage_bps: Number(slippage), fixed_fee: 0 } };
            const created = await request("/trading/experiments", { dataset_id: datasetId, config, candidates: parsedCandidates(), train_sessions: Number(train), validation_sessions: Number(validation), final_sessions: Number(finalSessions), cost_multipliers: multipliers.split(",").map(Number), finalize: false });
            setExperimentId(created.id); setJob(created); setExperiment(null); setAttemptEvidence(null);
            setNotice(`Experiment ${created.id} registered. The final test remains reserved.`);
        });
    }

    const quality = dataset?.quality || dataset?.quality_report;
    const split = experiment?.split;
    const attempts = experiment?.attempts || [];
    const finalizable = job?.status === "complete" && experiment && !split?.final_test_accessed && !job.request?.experiment?.finalize && job.request?.experiment;
    const periods = (values) => values?.length ? values.join(", ") : "Unavailable";
    return <section className="research-dashboard" aria-label="Strategy research">
        <h3>Strategy research</h3>
        <p className="trading-notice">Compare simulated strategies on one immutable dataset with shared capital, risk limits and costs. Synthetic results demonstrate mechanics; they cannot establish a market edge. Historical LLM evaluations may contain training-data contamination and nondeterministic decisions.</p>
        {error && <p className="error" role="alert">{error}</p>}
        {connectionError && <p className="error" role="alert">Research connection failed: {connectionError}. Displayed evidence is the last received snapshot.</p>}
        {notice && <p role="status">{notice}</p>}
        <details className="research-registry"><summary>Versioned strategy registry ({strategies.length})</summary>{strategies.map((strategy) => <article key={`${strategy.id}-${strategy.version}`}><h4>{strategy.id} · {strategy.version}{strategy.experimental ? " · Experimental" : ""}</h4><p>{strategy.hypothesis}</p><dl><dt>Required observations</dt><dd>{display(strategy.required_observations)}</dd><dt>Warm-up</dt><dd>{display(strategy.warmup)}</dd><dt>Failure conditions</dt><dd>{display(strategy.failure_conditions)}</dd><dt>Prerequisites</dt><dd>{display(strategy.prerequisites)}</dd></dl><details><summary>Parameter contract</summary><pre>{display(strategy.parameters)}</pre></details></article>)}</details>
        <div className="research-forms">
            <form onSubmit={createDataset}>
                <h4>Preserve a dataset</h4>
                <label>Dataset source<select value={source} onChange={(event) => setSource(event.target.value)}><option value="synthetic">Synthetic fixture</option><option value="yahoo">Yahoo aggregated bars</option></select></label>
                <label>Dataset symbols<input required value={symbols} onChange={(event) => setSymbols(event.target.value)} /></label>
                <label>Dataset start date<input type="date" required value={start} onChange={(event) => setStart(event.target.value)} /></label>
                <label>Dataset end date (inclusive)<input type="date" required min={start} value={end} onChange={(event) => setEnd(event.target.value)} /></label>
                <label>Dataset bar interval<select value={interval} onChange={(event) => setIntervalValue(event.target.value)}>{["1m", "2m", "5m", "15m", "30m", "60m"].map((value) => <option key={value}>{value}</option>)}</select></label>
                <small>Aggregated OHLCV bars contain no trade or quote sequence. Missing observations stay missing. Synthetic fixture seed: 17.</small>
                <button className="primary-btn" disabled={busy || inProgress(datasetJob?.status)}>Create immutable dataset</button>
                {datasetJob && <p className="meta">Dataset job <code>{datasetJob.id}</code> · {datasetJob.status}</p>}
                {datasetJob?.error && <p className="error" role="alert">{datasetJob.error}</p>}
            </form>
            <form onSubmit={runExperiment}>
                <h4>Register a validation experiment</h4>
                <label>Immutable dataset<select required value={datasetId} onChange={(event) => { setDatasetId(event.target.value); setDataset(null); }}><option value="">Select a preserved dataset</option>{datasets.map((item) => <option value={identifier(item)} key={identifier(item)}>{identifier(item)} · {item.source || item.request?.source}</option>)}</select></label>
                <label>Candidate configurations (JSON)<textarea rows="9" value={candidates} onChange={(event) => setCandidates(event.target.value)} /></label>
                <small>Use registry IDs and exact versions. Add parameter variants as separate candidates; every attempt is recorded.</small>
                <button type="button" className="ghost-btn" disabled={busy} onClick={() => act(async () => { const values = parsedCandidates(); for (const candidate of values) await request("/trading/strategies/validate", candidate); setNotice(`${values.length} candidate configurations validated.`); })}>Validate parameters</button>
                <div className="research-input-row"><label>Training sessions<input type="number" min="2" required value={train} onChange={(event) => setTrain(event.target.value)} /></label><label>Validation sessions per fold<input type="number" min="1" required value={validation} onChange={(event) => setValidation(event.target.value)} /></label><label>Reserved final sessions<input type="number" min="2" required value={finalSessions} onChange={(event) => setFinalSessions(event.target.value)} /></label></div>
                <div className="research-input-row"><label>Research capital (USD)<input type="number" min="1" required value={cash} onChange={(event) => setCash(event.target.value)} /></label><label>Commission (bps)<input type="number" min="0" max="1000" required value={commission} onChange={(event) => setCommission(event.target.value)} /></label><label>Slippage (bps)<input type="number" min="0" max="1000" required value={slippage} onChange={(event) => setSlippage(event.target.value)} /></label></div>
                <label>Cost stress multipliers<input value={multipliers} required onChange={(event) => setMultipliers(event.target.value)} /></label>
                <small>Host risk controls apply to every strategy. Chronological walk-forward validation chooses a candidate; the final test is reserved.</small>
                <button className="primary-btn" disabled={busy || !dataset}>Run validation experiment</button>
            </form>
        </div>
        {dataset && <section aria-label="Dataset evidence"><h4>Dataset evidence · <code>{datasetId}</code></h4><p>{dataset.source || dataset.request?.source} · {dataset.observation_type === "aggregated_ohlcv" ? "aggregated OHLCV bars" : dataset.observation_type || "aggregated OHLCV bars"} · {dataset.request?.start} → {dataset.request?.end}</p><details open><summary>Data quality report</summary>{quality?.usable !== undefined && <p>Research usability: {quality.usable ? "passed current checks" : "rejected — inspect errors"}</p>}<pre>{quality ? display(quality) : "Quality report unavailable. Do not assume complete observations."}</pre></details><details><summary>Provenance, adjustments and checksums</summary><pre>{display(dataset)}</pre></details></section>}
        <section aria-label="Saved research experiments"><h4>Saved experiments</h4>{!experiments.length && <p className="meta">No research records yet.</p>}<div className="research-experiment-list">{experiments.map((item) => { const id = identifier(item); return <div key={id}><button type="button" aria-pressed={experimentId === id} onClick={() => { setExperimentId(id); setExperiment(null); setJob(null); setAttemptEvidence(null); }}>{id} · {item.status}</button><label><input type="checkbox" aria-label={`Compare ${id}`} checked={comparisonIds.includes(id)} onChange={(event) => setComparisonIds((current) => event.target.checked ? [...current, id] : current.filter((value) => value !== id))} />Compare</label></div>; })}</div><button type="button" className="ghost-btn" disabled={busy || comparisonIds.length < 2} onClick={() => act(async () => { setComparison(null); setComparison(await request("/trading/experiments/compare", { experiment_ids: comparisonIds })); })}>Compare selected experiments</button>{comparison && <section aria-label="Comparable experiment results"><h4>Comparable experiment results</h4><p className="meta">Shared dataset: <code>{comparison.dataset_id}</code> · Protocol: <code>{comparison.protocol_id}</code></p><div className="trading-table"><table><thead><tr><th>Experiment</th><th>Assessment</th><th>Selected strategy</th><th>Validation excess sum (pp)</th><th>Net return</th><th>Benchmark return</th><th>Max drawdown</th><th>Commissions</th><th>Slippage</th></tr></thead><tbody>{comparison.experiments?.map((item) => <tr key={item.experiment_id}><td>{item.experiment_id}</td><td>{display(item.assessment)}</td><td>{item.selected_strategy?.kind || "Unavailable"}</td><td>{Number.isFinite(item.metrics?.validation_excess_sum_pct) ? `${item.metrics.validation_excess_sum_pct.toFixed(2)} pp` : "Unavailable"}</td><Metrics metrics={item.metrics} /></tr>)}</tbody></table></div></section>}</section>
        {job && <section aria-label="Experiment evidence"><div className="trading-heading"><h4>Experiment <code>{experimentId}</code> · {job.status}</h4>{inProgress(job.status) && <button type="button" className="ghost-btn" disabled={busy || job.status === "stopping"} onClick={() => act(async () => { setJob(await request(`/trading/experiments/${experimentId}/stop`, {})); })}>Cancel experiment</button>}</div>{job.error && <p role="alert" className="error">{job.error}</p>}<p className="meta">Dataset: <code>{experiment?.dataset_id || job.request?.experiment?.dataset_id || "Awaiting evidence"}</code></p>
            <p className="trading-notice">Evidence assessment: {display(experiment?.assessment || "Inconclusive — experiment has not produced a verified assessment.")}</p>
            {experiment?.assessment_reason && <p>{experiment.assessment_reason}</p>}
            {job.progress && <p className="meta">Completed attempts: {job.progress.attempts_completed ?? 0} · Current session: {job.progress.session || "Awaiting session"} · Completed bars: {job.progress.completed_bars ?? 0}</p>}
            {experiment?.selected_strategy && <p>Selected configuration: <code>{display(experiment.selected_strategy)}</code></p>}
            {experiment?.parameter_sensitivity && <details><summary>Parameter sensitivity within this experiment</summary><p>{experiment.selection_rule}</p><pre>{display(experiment.parameter_sensitivity)}</pre></details>}
            {split && <div className="research-periods"><h4>Chronological evaluation periods</h4><p>Initial training: {periods(split.training_sessions)}</p>{split.validation_folds?.map((fold, index) => <p key={index}>Fold {index + 1} · Training: {periods(fold.train)} · Validation: {periods(fold.validation)}</p>)}<p>Final test — {split.final_test_accessed ? "accessed" : "reserved, not evaluated"}: {periods(split.final_sessions)}</p></div>}
            {experiment?.errors?.length > 0 && <div role="alert" className="error"><h4>Experiment failures</h4><pre>{display(experiment.errors)}</pre></div>}
            {experiment?.multiple_testing && <details><summary>Multiple-testing risk and research limitations</summary><pre>{display(experiment.multiple_testing)}</pre>{experiment.limitations?.map((limitation) => <p key={limitation}>{limitation}</p>)}</details>}
            {finalizable && <div className="trading-notice"><p>The reserved final test can be accessed once for this dataset. This evaluates the frozen selected configuration and benchmarks without reselection.</p><button type="button" className="ghost-btn" disabled={busy} onClick={() => act(async () => { const created = await request("/trading/experiments", { ...job.request.experiment, finalize: true, parent_experiment_id: job.id }); setExperimentId(created.id); setJob(created); setExperiment(null); setAttemptEvidence(null); setNotice(`Final test experiment ${created.id} registered.`); })}>Evaluate reserved final test once</button></div>}
            {!!attempts.length && <><h4>Recorded attempts · {attempts.length}</h4><div className="trading-table"><table><thead><tr><th>Strategy / version</th><th>Period / fold</th><th>Cost multiplier</th><th>Status</th><th>Net return</th><th>Benchmark return</th><th>Max drawdown</th><th>Commissions</th><th>Slippage</th><th>Audit</th></tr></thead><tbody>{attempts.map((attempt) => <tr key={attempt.attempt_id}><td>{attempt.strategy?.kind} / {attempt.strategy?.version}</td><td>{attempt.period} / {attempt.fold ?? "—"}</td><td>{attempt.cost_multiplier}×</td><td>{attempt.status}</td><Metrics metrics={attempt.metrics} /><td><button type="button" className="ghost-btn" disabled={busy} onClick={() => act(async () => { setAttemptEvidence(await request(`/trading/experiments/${experimentId}/attempts/${attempt.attempt_id}`)); })}>Review {attempt.attempt_id}</button></td></tr>)}</tbody></table></div><details><summary>Attempt IDs, reconciliation and audit evidence</summary><pre>{display(attempts)}</pre></details></>}
            {attemptEvidence && <section aria-label="Attempt evidence"><h4>Attempt evidence · <code>{attemptEvidence.attempt_id}</code></h4>{attemptEvidence.truncated && <p className="trading-notice">Showing bounded recent observations, decisions and fills. Full ledgers remain in the recorded artifact.</p>}{attemptEvidence.sessions?.map((session) => <details open key={session.session}><summary>Session {session.session} · {session.status}</summary><AttemptChart session={session} /><h4>Simulated fills</h4>{!session.fills?.length ? <p>No fills recorded in this snapshot.</p> : <div className="trading-table"><table><thead><tr><th>Time (UTC)</th><th>Symbol</th><th>Side</th><th>Shares</th><th>Reference price</th><th>Fill price</th><th>Commission</th><th>Slippage</th></tr></thead><tbody>{session.fills.map((fill, index) => <tr key={index}><td>{fill.timestamp}</td><td>{fill.symbol}</td><td>{fill.side}</td><td>{fill.quantity}</td><td>{money(fill.reference_price)}</td><td>{money(fill.fill_price)}</td><td>{money(fill.commission)}</td><td>{money(fill.slippage_cost)}</td></tr>)}</tbody></table></div>}<h4>Decisions and host risk controls</h4><ul className="trading-decisions">{session.decisions?.map((decision, index) => <li key={index}><small>{decision.timestamp}</small><p>{decision.error || decision.reason}</p><p>Proposed weights: <code>{display(decision.requested_weights)}</code></p><p>Host accepted weights: <code>{display(decision.accepted_weights)}</code></p>{decision.policy_audit && <details><summary>Experimental model response</summary><pre>{display(decision.policy_audit)}</pre></details>}</li>)}</ul>{!!session.events?.length && <details><summary>Operational events</summary><pre>{display(session.events)}</pre></details>}</details>)}<details><summary>Reconciliation and artifact references</summary><pre>{display({ reconciliation: attemptEvidence.reconciliation || attemptEvidence.reconciliations, artifact_ref: attemptEvidence.artifact_ref })}</pre></details></section>}
            {experiment && <details><summary>Registered specification and evidence</summary><pre>{display(experiment)}</pre></details>}
        </section>}
    </section>;
}
