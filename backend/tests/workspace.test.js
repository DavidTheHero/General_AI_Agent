import test from "node:test";
import assert from "node:assert/strict";
import request from "supertest";
import { createWorkspace, workspaceRequest, quarterlySeries, alignedPerformance } from "../finance/workspace.js";
import { createApp } from "../app.js";
import { createAgent } from "../agent.js";
import { createTools } from "../tools.js";
import { createChains } from "../llm.js";

const table = (columns, index, rows) => ({ columns, index, rows });
const periods = ["2026-09-30T00:00:00", "2026-06-30T00:00:00", "2026-03-31T00:00:00", "2025-12-31T00:00:00"];
test("real Ollama chains initialize with workspace JSON schemas without network calls", () => {
    assert.ok(createChains().workspace);
});
function fakeFinance(fail = null) {
    const calls = [];
    return { calls, call: async (name, args) => {
        calls.push({ name, args });
        if (fail?.(name, args)) throw new Error("Provider unavailable");
        if (name === "stock_quote") return { symbol: args.symbol, price: 120, currency: "USD", date: "2026-10-14", percent_change: 2, source: "Yahoo Finance via yfinance" };
        if (name === "exchange_rate") return { rate: .8, date: "2026-10-14", source: "Yahoo Finance via yfinance" };
        let data;
        if (name === "ticker_data") {
            if (args.dataset === "info") data = { shortName: `Company ${args.symbol}`, financialCurrency: "USD", currency: "USD", sector: "Technology", marketCap: 1e9, trailingPE: 20, forwardPE: 18, longBusinessSummary: "Company description" };
            if (args.dataset === "income_stmt") data = table(periods, ["TotalRevenue", "OperatingIncome", "NetIncome"], [[200, 100, 90, 80], [40, 10, 9, 8], [30, 5, 4, 3]]);
            if (args.dataset === "cash_flow") data = table(periods, ["OperatingCashFlow", "CapitalExpenditure"], [[50, 20, 19, 18], [-10, -5, -4, -3]]);
            if (args.dataset === "analyst_price_targets") data = { mean: 150 };
            if (args.dataset === "calendar") data = { "Earnings Date": ["2026-11-01"] };
            if (args.dataset === "news") data = [{ content: { title: "Company news", canonicalUrl: { url: "https://example.com/article" }, pubDate: "2026-10-14T12:00:00Z" } }];
        }
        if (name === "price_history") data = { prices: table(["Close"], ["2026-10-01T00:00:00", "2026-10-02T00:00:00", "2026-10-03T00:00:00"], args.symbol.includes("=X") ? [[.75], [.75], [.75]] : [[100], [110], [120]]) };
        if (name === "fund_data") data = table(["Name", "Holding Percent"], args.symbol === "SPY" ? ["NVDA", "AAPL"] : ["NVDA", "MSFT"], args.symbol === "SPY" ? [["Nvidia", .1], ["Apple", .08]] : [["Nvidia", .15], ["Microsoft", .1]]);
        if (name === "screen_instruments") data = { quotes: [{ symbol: "NVDA", shortName: "Nvidia", trailingPE: 20, regularMarketPrice: 120, currency: "USD" }] };
        if (name === "calendar_events") data = table(["Company"], ["2026-10-15"], [["Example"]]);
        if (name === "search_finance") data = [{ content: { title: "Market news", canonicalUrl: { url: "https://example.com/news" } } }];
        return { data, source: "Yahoo Finance via yfinance", retrieved_at: "2026-10-15T08:00:00Z", truncated: false };
    } };
}

test("research brief computes quarterly metrics and includes source evidence", async () => {
    const report = await createWorkspace(fakeFinance()).run({ workflow: "research", symbol: "NVDA" });
    assert.equal(report.data.quarters.at(-1).revenue, 200);
    assert.equal(report.data.quarters.at(-1).free_cashflow, 40);
    assert.equal(report.data.changes.revenue_qoq_pct, 100);
    assert.equal(report.data.quarters.at(-1).operating_margin, 20);
    assert.equal(report.data.news[0].url, "https://example.com/article");
    assert.equal(report.sources.length, 7);
    assert.equal(report.data.profile.financial_currency, "USD");
});

test("earnings explorer preserves null values and aligns cashflow by date", () => {
    const income = table(periods.slice(0, 2), ["TotalRevenue", "OperatingIncome"], [[null, 100], [0, 20]]);
    const cash = table([periods[1]], ["FreeCashFlow"], [[15]]);
    const series = quarterlySeries(income, cash);
    assert.equal(series[0].free_cashflow, 15);
    assert.equal(series[1].free_cashflow, null);
    assert.equal(series[1].revenue, null);
    assert.equal(series[1].operating_income, 0);
    assert.equal(series[1].operating_margin, null);
});

test("comparison uses common fiscal periods and adjusted common price dates", async () => {
    const finance = fakeFinance();
    const report = await createWorkspace(finance).run({ workflow: "comparison", symbols: ["NVDA", "AMD"] });
    assert.equal(report.data.common_period, "2026-09-30");
    assert.ok(finance.calls.filter(({ name }) => name === "price_history").every(({ args }) => args.adjusted));
    assert.equal(Math.round(report.data.performance.series[0].return_pct), 20);
    const aligned = alignedPerformance([
        { symbol: "A", rows: [{ date: "1", close: 100 }, { date: "2", close: 110 }, { date: "3", close: 120 }] },
        { symbol: "B", rows: [{ date: "2", close: 200 }, { date: "3", close: 220 }] },
    ]);
    assert.deepEqual(aligned.dates, ["2", "3"]);
    assert.equal(Math.round(aligned.series[1].return_pct), 10);
    assert.deepEqual(alignedPerformance([{ symbol: "A", rows: [] }, { symbol: "B", rows: [] }]).series, []);
});

test("ETF overlap is a lower bound from minimum shared available weights", async () => {
    const report = await createWorkspace(fakeFinance()).run({ workflow: "overlap", symbols: ["SPY", "QQQ"] });
    assert.equal(report.data.overlap_pct, 10);
    assert.equal(report.data.shared.length, 1);
    assert.equal(report.data.coverage[0].count, 2);
    assert.match(report.data.basis, /lower bound/);
    const missing = await createWorkspace(fakeFinance((name, args) => name === "fund_data" && args.symbol === "QQQ")).run({ workflow: "overlap", symbols: ["SPY", "QQQ"] });
    assert.equal(missing.data.overlap_pct, null);
});

test("screener exposes executed filters and explanations without invented metrics", async () => {
    const report = await createWorkspace(fakeFinance()).run({ workflow: "screener" });
    assert.equal(report.data.filters.operands.find(({ operands }) => operands[0] === "totaldebtequity.lasttwelvemonths").operands[1], 100);
    assert.match(report.data.matches[0].explanation, /100%/);
    assert.equal(report.data.matches[0].market_cap, null);
});

test("portfolio decomposes stock and FX effects and deduplicates identical FX calls", async () => {
    const finance = fakeFinance();
    const report = await createWorkspace(finance).run({ workflow: "portfolio", currency: "GBP", positions: [{ symbol: "NVDA", quantity: 10, cost_basis: 100, purchase_date: "2026-10-03" }, { symbol: "MSFT", quantity: 5 }] });
    assert.equal(report.data.total, 1440);
    const attribution = report.data.positions[0].attribution;
    assert.equal(attribution.stock_effect, 150);
    assert.ok(Math.abs(attribution.fx_effect - 60) < 1e-8);
    assert.equal(attribution.total_change, 210);
    assert.equal(finance.calls.filter(({ name }) => name === "exchange_rate").length, 1);
    const missing = await createWorkspace(fakeFinance((name) => name === "exchange_rate")).run({ workflow: "portfolio", currency: "GBP", positions: [{ symbol: "NVDA", quantity: 1 }] });
    assert.equal(missing.data.total, null);
    assert.equal(missing.data.complete, false);
});

test("morning brief uses declared benchmarks, dated calendars and watchlist", async () => {
    const report = await createWorkspace(fakeFinance()).run({ workflow: "morning", date: "2026-10-15", watchlist: ["NVDA"] });
    assert.deepEqual(report.data.benchmarks.map(({ symbol }) => symbol), ["^GSPC", "^IXIC", "^DJI"]);
    assert.equal(report.data.watchlist[0].symbol, "NVDA");
    assert.equal(report.data.date, "2026-10-15");
    assert.equal(report.data.news[0].title, "Market news");
});

test("provider failures produce partial reports and explicit warnings", async () => {
    const report = await createWorkspace(fakeFinance((name, args) => name === "ticker_data" && args.dataset === "cash_flow")).run({ workflow: "research", symbol: "NVDA" });
    assert.equal(report.data.profile.symbol, "NVDA");
    assert.equal(report.data.quarters.at(-1).free_cashflow, null);
    assert.match(report.warnings[0].message, /Provider unavailable/);
});

test("workspace API validates workflow inputs before finance calls", async () => {
    const finance = fakeFinance();
    const app = createApp({ agent: {}, store: {}, workspace: createWorkspace(finance), frontendPath: "/nonexistent" });
    await request(app).post("/finance/workspace").send({ workflow: "research", symbol: "NVDA" }).expect(200);
    for (const input of [{ workflow: "missing" }, { workflow: "comparison", symbols: ["NVDA"] }, { workflow: "portfolio", currency: "GBP", positions: [{ symbol: "NVDA", quantity: -1 }] }, { workflow: "portfolio", currency: "GBP", positions: [{ symbol: "NVDA", quantity: 1, cost_basis: 100 }] }, { workflow: "overlap", symbols: ["SPY", "SPY"] }]) await request(app).post("/finance/workspace").send(input).expect(400);
    assert.throws(() => workspaceRequest.parse({ workflow: "research", symbol: "NVDA; rm" }));
});

test("research requests in chat carry structured reports; missing inputs ask clarification", async () => {
    const tools = createTools(fetch, fakeFinance());
    const agent = createAgent({ tools, chains: { router: { invoke: async () => ({ tool_choice: "finance_workspace" }) }, workspace: { invoke: async () => ({ request: { workflow: "research", symbol: "NVDA" }, clarification: "" }) } } });
    const result = await agent.run("Research Nvidia");
    assert.equal(result.responses[0].report.workflow, "research");
    assert.equal(result.usage.finance_workspace, 1);
    const direct = createAgent({ tools, chains: { router: { invoke: async () => { throw new Error("Explicit research brief should not need routing"); } } } });
    assert.equal((await direct.run("Give me a company research brief on Nvidia")).responses[0].report.data.profile.symbol, "NVDA");
    const clarification = createAgent({ tools, chains: { router: { invoke: async () => ({ tool_choice: "finance_workspace" }) }, workspace: { invoke: async () => ({ request: null, clarification: "Which company?" }) } } });
    assert.match((await clarification.run("Research a company")).answer, /Which company/);
});
