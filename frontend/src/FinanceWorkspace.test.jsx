import React from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import FinanceWorkspace from "./FinanceWorkspace.jsx";
import FinanceReport, { LineChart } from "./FinanceReport.jsx";

const profile = { symbol: "NVDA", name: "Nvidia", sector: "Technology", financial_currency: "USD", currency: "USD", price: 120, price_date: "2026-10-14", source_url: "https://finance.yahoo.com/quote/NVDA/" };
const quarter = { period: "2026-09-30", revenue: 200, net_income: null, operating_margin: 20, operating_cashflow: 50, free_cashflow: 40 };
function report(workflow = "research") {
    const data = {
        research: { profile, quarters: [quarter], changes: { revenue_qoq_pct: 10 }, observations: ["Revenue increased 10%."], news: [], analyst_targets: null, calendar: null },
        earnings: { profile, quarters: [quarter], changes: {}, observations: [] },
        comparison: { companies: [{ ...profile, quarter }], common_period: "2026-09-30", performance: { dates: ["2026-01-01", "2026-01-02"], series: [{ symbol: "NVDA", values: [0, 10], return_pct: 10 }] } },
        overlap: { funds: [{ symbol: "SPY" }, { symbol: "QQQ" }], shared: [], overlap_pct: null, coverage: [{ symbol: "SPY", count: 0, weight_pct: null }] },
        screener: { criteria: { sector: "Technology", max_pe: 30, max_debt_equity: 100 }, matches: [], filters: {} },
        portfolio: { currency: "GBP", positions: [{ symbol: "NVDA", quantity: 1, display_value: null }], total: null, complete: false, available_subtotal: 0 },
        morning: { date: "2026-10-15", timezone: "Europe/London", benchmarks: [], watchlist: [], earnings: null, economic: null, news: [] },
    }[workflow];
    return { workflow, generated_at: "2026-10-15T08:00:00Z", data: { ...data, basis: "Reported data with source dates." }, warnings: [], sources: [] };
}

beforeEach(() => { vi.stubGlobal("fetch", vi.fn(async (_url, options) => ({ ok: true, json: async () => report(JSON.parse(options.body).workflow) }))); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("generates a sourced research report with charts and missing values", async () => {
    const user = userEvent.setup();
    render(<FinanceWorkspace />);
    await user.click(screen.getByRole("button", { name: "Generate report" }));
    expect(await screen.findByRole("heading", { name: "Nvidia NVDA" })).toBeTruthy();
    expect(screen.getByRole("img", { name: /Quarterly revenue/ })).toBeTruthy();
    expect(screen.getAllByText("Unavailable").length).toBeGreaterThan(0);
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ workflow: "research", symbol: "NVDA" });
});

it("all seven workflow forms submit their explicit inputs and render results", async () => {
    const user = userEvent.setup();
    render(<FinanceWorkspace />);
    for (const [button, workflow] of [["Compare companies", "comparison"], ["Earnings explorer", "earnings"], ["ETF overlap", "overlap"], ["Stock screener", "screener"], ["Portfolio & FX", "portfolio"], ["Market brief", "morning"]]) {
        await user.click(screen.getByRole("button", { name: button, exact: true }));
        await user.click(screen.getByRole("button", { name: "Generate report" }));
        await waitFor(() => expect(screen.queryByRole("status")).toBeNull());
        const input = JSON.parse(fetch.mock.calls.at(-1)[1].body);
        expect(input.workflow).toBe(workflow);
        if (workflow === "portfolio") expect(input.positions).toEqual([{ symbol: "NVDA", quantity: 10 }, { symbol: "MSFT", quantity: 5 }]);
        expect(screen.getByText("Reported data with source dates.")).toBeTruthy();
    }
});

it("blocks repeated requests while pending and shows backend validation errors", async () => {
    let finish;
    fetch.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    const user = userEvent.setup();
    render(<FinanceWorkspace />);
    await user.click(screen.getByRole("button", { name: "Generate report" }));
    expect(screen.getByRole("button", { name: "Building report…" }).disabled).toBe(true);
    finish({ ok: false, json: async () => ({ detail: "Use distinct symbols" }) });
    expect(await screen.findByRole("alert")).toHaveProperty("textContent", "Use distinct symbols");
});

it("renders incomplete portfolios without presenting a false total", () => {
    render(<FinanceReport report={report("portfolio")} />);
    expect(screen.getByText("Total unavailable (incomplete prices or FX)")).toBeTruthy();
    expect(screen.getByText("Available subtotal")).toBeTruthy();
});

it("report follow-up prepares a cashflow question for chat", async () => {
    const callback = vi.fn();
    const user = userEvent.setup();
    render(<FinanceReport report={report()} onFollowup={callback} />);
    await user.click(screen.getByRole("button", { name: "Explain cash flow in chat" }));
    expect(callback.mock.calls[0][0].query).toContain("NVDA");
});

it("chart legend can hide a series and source links cannot execute script", async () => {
    const user = userEvent.setup();
    const { unmount } = render(<LineChart title="Performance" labels={["A", "B"]} series={[{ name: "NVDA", values: [0, 10] }]} unit="%" />);
    await user.click(screen.getByRole("button", { name: "NVDA" }));
    expect(screen.getByRole("button", { name: "NVDA" }).getAttribute("aria-pressed")).toBe("false");
    expect(screen.getByText("No chart data available.")).toBeTruthy();
    unmount();
    const bad = report(); bad.data.profile.source_url = "javascript:alert(1)";
    render(<FinanceReport report={bad} />);
    expect(screen.queryByRole("link", { name: "Company source" })).toBeNull();
});
