import React from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ResearchDashboard from "./ResearchDashboard.jsx";

const datasetId = "d".repeat(64), experimentId = "a".repeat(32), secondId = "b".repeat(32);
const dataset = { dataset_id: datasetId, source: "SYNTHETIC fixture", observation_type: "aggregated OHLCV bars", request: { symbols: ["SPY"], start: "2026-09-01", end: "2026-09-18", interval: "5m" }, quality: { gaps: ["2026-09-03 missing completed bar"], duplicates: 0 }, checksums: { observations: "sha256:verified" } };
const specification = { dataset_id: datasetId, config: { symbols: ["SPY"], interval: "5m", initial_cash: 100000 }, candidates: [{ kind: "trend_following", version: "1.0.0", fast_window: 3 }], train_sessions: 2, validation_sessions: 1, final_sessions: 2, cost_multipliers: [1, 2], finalize: false };
const result = { experiment_id: experimentId, dataset_id: datasetId, assessment: "inconclusive", split: { training_sessions: ["2026-09-01", "2026-09-02"], validation_folds: [{ train: ["2026-09-01", "2026-09-02"], validation: ["2026-09-03"] }], final_sessions: ["2026-09-16", "2026-09-17"], final_test_accessed: false }, attempts: [{ attempt_id: "attempt-1", strategy: specification.candidates[0], period: "validation", fold: 1, cost_multiplier: 2, status: "complete", metrics: { return_pct: 1.23, max_drawdown_pct: 0.5, commission_cost: 12.34, slippage_cost: 24.68 }, reconciliation: { passed: true } }] };
const job = { id: experimentId, status: "complete", request: { experiment: specification }, experiment: result };
const registry = { strategies: [{ id: "trend_following", version: "1.0.0", hypothesis: "Persistent trends may exceed modeled trading costs.", warmup: "12 completed bars", required_observations: ["completed OHLCV"], failure_conditions: ["stale data"], prerequisites: ["USD long-only"], parameters: {} }] };
const ok = (value) => ({ ok: true, json: async () => value });

function mockRequests({ detail = job, experiments = [result] } = {}) {
    fetch.mockImplementation(async (url) => {
        if (url === "/trading/strategies") return ok(registry);
        if (url === "/trading/datasets") return ok({ datasets: [dataset] });
        if (url === `/trading/datasets/${datasetId}`) return ok(dataset);
        if (url === "/trading/experiments") return ok({ experiments });
        if (url === `/trading/experiments/${experimentId}`) return ok(detail);
        throw new Error(`Unexpected request ${url}`);
    });
}

beforeEach(() => { vi.stubGlobal("fetch", vi.fn()); mockRequests(); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("shows immutable data quality, validation costs and reserved periods without claiming an edge", async () => {
    render(<ResearchDashboard pollMs={60000} />);
    expect(await screen.findByText(/Evidence assessment: inconclusive/)).toBeTruthy();
    expect(screen.getByText(/SYNTHETIC fixture.*aggregated OHLCV bars/, { selector: "p" })).toBeTruthy();
    expect(screen.getAllByText(/missing completed bar/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Final test — reserved, not evaluated: 2026-09-16, 2026-09-17/)).toBeTruthy();
    const row = screen.getByRole("row", { name: /trend_following \/ 1.0.0/ });
    expect(within(row).getByText("validation / 1")).toBeTruthy();
    expect(within(row).getByText("1.23%")).toBeTruthy();
    expect(within(row).getByText("$12.34")).toBeTruthy();
    expect(within(row).getByText("$24.68")).toBeTruthy();
    expect(within(row).getByText("Unavailable")).toBeTruthy();
    expect(fetch.mock.calls.every(([, options]) => options.method !== "POST")).toBe(true);
});

it("creates exactly the requested dataset and registers shared-cost validation with an untouched final test", async () => {
    const user = userEvent.setup();
    const original = fetch.getMockImplementation();
    fetch.mockImplementation(async (url, options) => {
        if (options?.method === "POST") return ok({ id: secondId, status: "running" });
        if (url === `/trading/jobs/${secondId}`) return ok({ id: secondId, status: "failed", error: "Unavailable requested history" });
        if (url === `/trading/experiments/${secondId}`) return ok({ id: secondId, status: "running" });
        return original(url, options);
    });
    render(<ResearchDashboard pollMs={60000} />);
    await screen.findByText(/Evidence assessment/);
    await user.selectOptions(screen.getByLabelText("Dataset source"), "yahoo");
    await user.clear(screen.getByLabelText("Dataset start date"));
    await user.type(screen.getByLabelText("Dataset start date"), "2026-09-02");
    await user.selectOptions(screen.getByLabelText("Dataset bar interval"), "15m");
    await user.click(screen.getByRole("button", { name: "Create immutable dataset" }));
    const dataCall = fetch.mock.calls.find(([url, options]) => url === "/trading/datasets" && options?.method === "POST");
    expect(JSON.parse(dataCall[1].body)).toEqual({ source: "yahoo", symbols: ["SPY"], start: "2026-09-02", end: "2026-09-18", interval: "15m" });
    expect(await screen.findByRole("alert")).toHaveProperty("textContent", "Unavailable requested history");
    await user.click(screen.getByRole("button", { name: "Run validation experiment" }));
    const experimentCall = fetch.mock.calls.find(([url, options]) => url === "/trading/experiments" && options?.method === "POST");
    const payload = JSON.parse(experimentCall[1].body);
    expect(payload.dataset_id).toBe(datasetId);
    expect(payload.config).toEqual({ symbols: ["SPY"], interval: "5m", initial_cash: 100000, costs: { commission_bps: 1, slippage_bps: 2, fixed_fee: 0 } });
    expect(payload.candidates.map((candidate) => candidate.kind)).toEqual(["trend_following", "mean_reversion", "opening_range_breakout"]);
    expect(payload).toMatchObject({ train_sessions: 2, validation_sessions: 1, final_sessions: 2, cost_multipliers: [1, 2], finalize: false });
});

it("finalizes the immutable parent specification even after the form is edited", async () => {
    const user = userEvent.setup();
    const original = fetch.getMockImplementation();
    fetch.mockImplementation(async (url, options) => options?.method === "POST" ? ok({ id: secondId, status: "running" }) : url.endsWith(secondId) ? ok({ id: secondId, status: "running" }) : original(url, options));
    render(<ResearchDashboard pollMs={60000} />);
    await screen.findByRole("button", { name: "Evaluate reserved final test once" });
    await user.clear(screen.getByLabelText("Research capital (USD)"));
    await user.type(screen.getByLabelText("Research capital (USD)"), "123");
    await user.click(screen.getByRole("button", { name: "Evaluate reserved final test once" }));
    const payload = JSON.parse(fetch.mock.calls.find(([url, options]) => url === "/trading/experiments" && options?.method === "POST")[1].body);
    expect(payload).toEqual({ ...specification, finalize: true, parent_experiment_id: experimentId });
});

it("keeps recorded evidence visible after polling and strict-comparison failures", async () => {
    const user = userEvent.setup();
    mockRequests({ experiments: [result, { ...result, experiment_id: secondId }] });
    render(<ResearchDashboard pollMs={20} />);
    await screen.findByText(/Evidence assessment: inconclusive/);
    const original = fetch.getMockImplementation();
    fetch.mockImplementation(async (url, options) => url === "/trading/experiments/compare" ? { ok: false, json: async () => ({ detail: "Experiments use different datasets or protocols" }) } : original(url, options));
    await user.click(screen.getByRole("checkbox", { name: `Compare ${experimentId}` }));
    await user.click(screen.getByRole("checkbox", { name: `Compare ${secondId}` }));
    await user.click(screen.getByRole("button", { name: "Compare selected experiments" }));
    expect(await screen.findByRole("alert")).toHaveProperty("textContent", "Experiments use different datasets or protocols");
    fetch.mockRejectedValue(new Error("Runtime unavailable"));
    await screen.findByText(/Displayed evidence is the last received snapshot/);
    expect(screen.getByText(/Evidence assessment: inconclusive/)).toBeTruthy();
    expect(screen.getByRole("row", { name: /trend_following \/ 1.0.0/ })).toBeTruthy();
    expect(screen.getByText("Experiments use different datasets or protocols")).toBeTruthy();
});

it("cancels a running experiment and stops polling after unmount", async () => {
    const user = userEvent.setup();
    mockRequests({ detail: { ...job, status: "running", experiment: null } });
    const original = fetch.getMockImplementation();
    fetch.mockImplementation(async (url, options) => url.endsWith("/stop") ? ok({ ...job, status: "stopping", experiment: null }) : original(url, options));
    const { unmount } = render(<ResearchDashboard pollMs={30} />);
    await user.click(await screen.findByRole("button", { name: "Cancel experiment" }));
    expect(fetch.mock.calls.some(([url, options]) => url === `/trading/experiments/${experimentId}/stop` && options?.method === "POST")).toBe(true);
    unmount();
    const calls = fetch.mock.calls.length;
    await new Promise((resolve) => setTimeout(resolve, 80));
    expect(fetch.mock.calls.length).toBe(calls);
});

it("validates each configured strategy before reporting success", async () => {
    const user = userEvent.setup();
    const original = fetch.getMockImplementation();
    fetch.mockImplementation(async (url, options) => url === "/trading/strategies/validate" ? ok({ valid: true }) : original(url, options));
    render(<ResearchDashboard pollMs={60000} />);
    await screen.findByText(/Evidence assessment/);
    await user.click(screen.getByRole("button", { name: "Validate parameters" }));
    expect(await screen.findByRole("status")).toHaveProperty("textContent", "3 candidate configurations validated.");
    const calls = fetch.mock.calls.filter(([url]) => url === "/trading/strategies/validate");
    expect(calls.map(([, options]) => JSON.parse(options.body).kind)).toEqual(["trend_following", "mean_reversion", "opening_range_breakout"]);
});

it("compares compatible experiments in a metric table with a shared dataset reference", async () => {
    const user = userEvent.setup();
    mockRequests({ experiments: [result, { ...result, experiment_id: secondId }] });
    const original = fetch.getMockImplementation();
    fetch.mockImplementation(async (url, options) => url === "/trading/experiments/compare" ? ok({ comparable: true, dataset_id: datasetId, protocol_id: "shared-protocol", experiments: [{ experiment_id: secondId, assessment: "inconclusive", selected_strategy: { kind: "mean_reversion" }, metrics: { return_pct: -1, max_drawdown_pct: 2, commission_cost: 4, slippage_cost: 8 } }] }) : original(url, options));
    render(<ResearchDashboard pollMs={60000} />);
    await screen.findByText(/Evidence assessment/);
    await user.click(screen.getByRole("checkbox", { name: `Compare ${experimentId}` }));
    await user.click(screen.getByRole("checkbox", { name: `Compare ${secondId}` }));
    await user.click(screen.getByRole("button", { name: "Compare selected experiments" }));
    const comparison = await screen.findByRole("region", { name: "Comparable experiment results" });
    expect(within(comparison).getByText("shared-protocol")).toBeTruthy();
    expect(within(comparison).getByRole("cell", { name: "mean_reversion" })).toBeTruthy();
    expect(within(comparison).getByRole("cell", { name: "-1.00%" })).toBeTruthy();
});

it("reviews bounded attempt fills and the target weights enforced by host risk controls", async () => {
    const user = userEvent.setup();
    const original = fetch.getMockImplementation();
    fetch.mockImplementation(async (url, options) => url.endsWith("/attempts/attempt-1") ? ok({ attempt_id: "attempt-1", experiment_id: experimentId, truncated: true, reconciliation: { passed: true }, sessions: [{ session: "2026-09-03", status: "complete", equity: [{ timestamp: "2026-09-03T13:30:00Z", equity: 100000, drawdown: -0.02 }, { timestamp: "2026-09-03T13:35:00Z", equity: 99000, drawdown: -0.0298 }], fills: [{ timestamp: "2026-09-03T13:35:00Z", symbol: "SPY", side: "buy", quantity: 10, reference_price: 100, fill_price: 100.02, commission: 1.23, slippage_cost: 2.34 }], decisions: [{ timestamp: "2026-09-03T13:30:00Z", reason: "Trend target was capped by position risk", requested_weights: { SPY: 0.9 }, accepted_weights: { SPY: 0.5 } }] }] }) : original(url, options));
    render(<ResearchDashboard pollMs={60000} />);
    await user.click(await screen.findByRole("button", { name: "Review attempt-1" }));
    const evidence = await screen.findByRole("region", { name: "Attempt evidence" });
    expect(within(evidence).getByText(/Showing bounded recent/)).toBeTruthy();
    expect(within(evidence).getByRole("img", { name: /Attempt equity and drawdown for session 2026-09-03, 2 displayed/ })).toBeTruthy();
    expect(within(evidence).getByText("-2.98%")).toBeTruthy();
    expect(within(evidence).getByText(/session drawdown · 2 observations shown/)).toBeTruthy();
    expect(within(evidence).getByText(/Proposed weights/).textContent).toContain('"SPY": 0.9');
    expect(within(evidence).getByText(/Host accepted weights/).textContent).toContain('"SPY": 0.5');
    expect(within(evidence).getByRole("cell", { name: "$1.23" })).toBeTruthy();
    expect(within(evidence).getByRole("cell", { name: "$2.34" })).toBeTruthy();
});
