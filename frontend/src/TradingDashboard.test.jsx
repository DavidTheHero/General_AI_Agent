import React from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import TradingDashboard from "./TradingDashboard.jsx";

const id = "a".repeat(32);
const job = {
    id, status: "running", simulation_only: true, created_at: "2026-10-14T13:00:00Z",
    request: { mode: "watch", config: { symbols: ["SPY"], initial_cash: 100000 } },
    progress: { source: "Yahoo Finance via yfinance", state: "observing", completed_bars: 1, cash: 90000,
        valuation_timestamp: "2026-10-14T13:35:00Z", equity: [{ timestamp: "2026-10-14T13:35:00Z", equity: 100100 }],
        holdings: { SPY: { quantity: 10, market_price: 1010, market_value: 10100 } },
        fills: [{ timestamp: "2026-10-14T13:30:00Z", symbol: "SPY", side: "buy", quantity: 10, fill_price: 1000 }],
        decisions: [{ timestamp: "2026-10-14T13:35:00Z", reason: "Positive trend observed" }] },
    artifacts: ["report.html"],
};
const ok = (value) => ({ ok: true, json: async () => value });

beforeEach(() => {
    window.history.replaceState(null, "", "/");
    vi.stubGlobal("fetch", vi.fn(async (url) => ok(url === "/trading/jobs" ? { jobs: [] } : job)));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); window.history.replaceState(null, "", "/"); });

it("launches an explicit demo and displays live evidence and safe report links", async () => {
    const user = userEvent.setup();
    fetch.mockImplementation(async (url, options) => ok(url === "/trading/jobs" && options?.method !== "POST" ? { jobs: [] } : job));
    render(<TradingDashboard pollMs={60000} />);
    await screen.findByText("Runtime connected");
    await user.click(screen.getByRole("button", { name: "Start simulation" }));
    const payload = JSON.parse(fetch.mock.calls.find(([, options]) => options?.method === "POST")[1].body);
    expect(payload.mode).toBe("demo");
    expect(payload.config.symbols).toEqual(["SPY", "AAPL"]);
    expect(payload.continuous).toBe(false);
    expect(await screen.findByRole("img", { name: /Simulated equity/ })).toBeTruthy();
    expect(screen.getByText("Positive trend observed")).toBeTruthy();
    expect(screen.getByRole("link", { name: "report.html" }).getAttribute("href")).toBe(`/trading/jobs/${id}/artifacts/report.html`);
    expect(window.location.search).toBe(`?trading_job=${id}`);
});

it("polls new bars, stops the selected job and cancels polling when unmounted", async () => {
    let status = "running", equity = 100100;
    fetch.mockImplementation(async (url) => {
        if (url.endsWith("/stop")) { status = "stopping"; return ok({ ...job, status }); }
        if (url === "/trading/jobs") return ok({ jobs: [job] });
        return ok({ ...job, status, progress: { ...job.progress, equity: [{ timestamp: "2026-10-14T13:35:00Z", equity }] } });
    });
    const user = userEvent.setup();
    const { unmount } = render(<TradingDashboard initialJob={id} pollMs={30} />);
    await screen.findByRole("img", { name: /to \$100,100\.00/ });
    equity = 100200;
    await screen.findByRole("img", { name: /to \$100,200\.00/ });
    await user.click(screen.getByRole("button", { name: "Stop simulation" }));
    expect(fetch.mock.calls.some(([url, options]) => url === `/trading/jobs/${id}/stop` && options.method === "POST")).toBe(true);
    await waitFor(() => expect(screen.getByRole("button", { name: "Stop simulation" }).disabled).toBe(true));
    unmount();
    const calls = fetch.mock.calls.length;
    await new Promise((resolve) => setTimeout(resolve, 80));
    expect(fetch.mock.calls.length).toBe(calls);
});

it("shows offline errors without starting or discarding a job", async () => {
    fetch.mockResolvedValue({ ok: false, json: async () => ({ detail: "Trading runtime is offline. Start npm run trading:runtime." }) });
    render(<TradingDashboard />);
    expect(await screen.findByRole("alert")).toHaveProperty("textContent", "Trading runtime is offline. Start npm run trading:runtime.");
    expect(fetch.mock.calls.every(([, options]) => options.method !== "POST")).toBe(true);
});

it("continuous watch is explicitly selected and synthetic data is never mislabeled as live", async () => {
    const user = userEvent.setup();
    fetch.mockImplementation(async (url, options) => ok(url === "/trading/jobs" && options?.method !== "POST" ? { jobs: [] } : { ...job, progress: { ...job.progress, source: "SYNTHETIC demonstration" } }));
    render(<TradingDashboard />);
    await user.selectOptions(screen.getByLabelText("Run mode"), "watch");
    await user.click(screen.getByLabelText("Continue across future sessions"));
    await user.click(screen.getByRole("button", { name: "Start simulation" }));
    expect(JSON.parse(fetch.mock.calls.find(([, options]) => options?.method === "POST")[1].body).continuous).toBe(true);
    expect(await screen.findByText(/SYNTHETIC demonstration/)).toBeTruthy();
});

it("keeps a rejected date-range explanation visible while successful status polls continue", async () => {
    const user = userEvent.setup();
    const error = "Yahoo 1-minute history is limited to approximately the most recent 30 days. Choose recent dates or 60m bars.";
    fetch.mockImplementation(async (_url, options) => options?.method === "POST" ? { ok: false, json: async () => ({ detail: error }) } : ok({ jobs: [] }));
    render(<TradingDashboard pollMs={20} />);
    await user.selectOptions(screen.getByLabelText("Run mode"), "backtest");
    await user.selectOptions(screen.getByLabelText("Bar interval"), "1m");
    expect(screen.getByText(/automatically fetched in 7-day batches/)).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Start simulation" }));
    expect(await screen.findByRole("alert")).toHaveProperty("textContent", error);
    const calls = fetch.mock.calls.length;
    await waitFor(() => expect(fetch.mock.calls.length).toBeGreaterThan(calls + 1));
    expect(screen.getByRole("alert").textContent).toBe(error);
    expect(screen.getByRole("button", { name: "Start simulation" }).disabled).toBe(false);
});

it("shows saved job failure reasons and the actual requested range", async () => {
    const error = "Yahoo Finance rejected the requested 1m date range";
    const failed = { ...job, status: "failed", error, progress: null, request: { mode: "backtest", start: "2026-01-01", end: "2026-10-01", config: { symbols: ["AAPL"], interval: "1m", initial_cash: 100 } } };
    fetch.mockImplementation(async (url) => ok(url === "/trading/jobs" ? { jobs: [failed] } : failed));
    render(<TradingDashboard initialJob={id} />);
    const saved = await screen.findByRole("button", { name: /AAPL.*backtest.*failed/ });
    expect(saved.textContent).toContain(error);
    expect(screen.getByText(/1m bars · Starting cash \$100.00 · 2026-01-01 → 2026-10-01/)).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toBe(error);
});
