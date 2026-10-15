import test from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { FinanceMcpClient } from "../finance/client.js";
import { createAgent } from "../agent.js";
import { createTools } from "../tools.js";

const fixture = fileURLToPath(new URL("../finance/tests/fixture_server.py", import.meta.url));

test("package MCP tools cover datasets, tables, discovery, queries and streaming offline", async (t) => {
    const client = new FinanceMcpClient({ args: [fixture] });
    t.after(() => client.close());
    const call = (name, args) => client.call(name, args);
    await client.connect();
    const resource = await client.client.readResource({ uri: "yfinance://capabilities" });
    const coverage = JSON.parse(resource.contents[0].text);
    assert.ok(coverage.coverage.FundsData);
    assert.ok(coverage.administrative_exclusions.Auth);
    for (const dataset of ["info", "fast_info", "isin", "history_metadata", "actions", "dividends", "splits", "capital_gains", "shares", "shares_full", "news", "calendar", "earnings_dates", "sec_filings", "income_stmt", "balance_sheet", "cash_flow", "earnings", "recommendations", "recommendations_summary", "upgrades_downgrades", "sustainability", "analyst_price_targets", "earnings_estimate", "revenue_estimate", "earnings_history", "eps_trend", "eps_revisions", "growth_estimates", "insider_purchases", "insider_transactions", "insider_roster_holders", "major_holders", "institutional_holders", "mutualfund_holders", "valuation", "options"]) {
        const value = await call("ticker_data", { symbol: "NVDA", dataset });
        assert.ok(value.source && value.retrieved_at, dataset);
        assert.equal(typeof value.truncated, "boolean");
    }
    const statement = await call("ticker_data", { symbol: "NVDA", dataset: "income_stmt", frequency: "trailing" });
    assert.equal(statement.data.arguments.freq, "trailing");
    const history = await call("price_history", { symbol: "NVDA", limit: 1, adjusted: true });
    assert.equal(history.data.adjusted, true);
    assert.equal(history.data.metadata.currency, "USD");
    assert.equal(history.data.prices.rows.length, 1);
    assert.equal(history.truncated, true);
    const batch = await call("download_prices", { symbols: ["NVDA", "MSFT"] });
    assert.deepEqual(batch.data.prices.columns[0], ["Close", "NVDA"]);
    assert.equal(batch.data.prices.rows[0][1], null);
    assert.equal((await call("search_finance", { query: "Nvidia", dataset: "news" })).data[0].title, "Example news");
    for (const category of ["all", "stock", "etf", "mutualfund", "index", "future", "currency", "cryptocurrency"]) {
        assert.equal((await call("lookup_instruments", { query: "Nvidia", category })).data.rows[0][1], `get_${category}`);
    }
    assert.equal((await call("market_data", { market: "GB", dataset: "status" })).data, null);
    for (const dataset of ["earnings", "economic_events", "ipo_info", "splits"]) {
        assert.equal((await call("calendar_events", { dataset, start: "2026-10-01", end: "2026-10-15" })).data.dataset, `get_${dataset}_calendar`);
    }
    for (const dataset of ["description", "quote_type", "fund_overview", "fund_operations", "asset_classes", "top_holdings", "equity_holdings", "bond_holdings", "bond_ratings", "sector_weightings"]) {
        assert.equal((await call("fund_data", { symbol: "SPY", dataset })).data.dataset, dataset);
    }
    assert.equal((await call("sector_data", { key: "technology" })).data.key, "technology");
    assert.equal((await call("industry_data", { key: "semiconductors" })).data.key, "semiconductors");
    assert.equal((await call("option_chain", { symbol: "NVDA", limit: 1 })).data.calls.rows.length, 1);
    for (const asset of ["equity", "fund", "etf"]) {
        const catalog = await call("screener_catalog", { asset });
        assert.ok(catalog.data.predefined.includes("day_gainers"));
        assert.ok(catalog.data.valid_fields.price.includes("intradayprice"));
        const screened = await call("screen_instruments", { asset, query: { operator: "gt", operands: ["intradayprice", 10] }, limit: 5 });
        assert.equal(screened.data.arguments.size, 5);
    }
    assert.equal((await call("screen_instruments", { predefined: "day_gainers" })).data.query, "day_gainers");
    const stream = await call("stream_prices", { symbols: ["NVDA"], limit: 2, seconds: 1 });
    assert.deepEqual(stream.data.messages.map(({ price }) => price), [100, 101]);
    assert.deepEqual((await call("stream_prices", { symbols: ["QUIET"], seconds: 1 })).data.messages, []);
});

test("package MCP rejects arbitrary access, malformed filters and excessive requests", async (t) => {
    const client = new FinanceMcpClient({ args: [fixture] });
    t.after(() => client.close());
    for (const [name, args] of [
        ["ticker_data", { symbol: "NVDA", dataset: "__dict__" }],
        ["price_history", { symbol: "NVDA", interval: "bad" }],
        ["price_history", { symbol: "NVDA", start: "not-a-date" }],
        ["price_history", { symbol: "NVDA", start: "2026-10-15", end: "2026-10-01" }],
        ["download_prices", { symbols: Array(11).fill("NVDA") }],
        ["ticker_data", { symbol: "NVDA", dataset: "info", limit: 501 }],
        ["calendar_events", { dataset: "earnings", start: "2026-01-01", end: "2026-12-31" }],
        ["option_chain", { symbol: "NVDA", expiry: "bad" }],
        ["screen_instruments", { query: { operator: "gt", operands: ["not_a_field", 10] } }],
        ["screen_instruments", { predefined: "missing" }],
        ["screen_instruments", { predefined: "day_gainers", query: {} }],
        ["stream_prices", { symbols: ["NVDA"], seconds: 11 }],
    ]) await assert.rejects(client.call(name, args), undefined, name);
});

test("chat discovers MCP schemas and executes package tools without stock comparison dispatch", async (t) => {
    const client = new FinanceMcpClient({ args: [fixture] });
    t.after(() => client.close());
    const agent = createAgent({ tools: createTools(fetch, client), chains: {
        router: { invoke: async () => ({ tool_choice: "finance_data" }) },
        finance: { invoke: async ({ available_tools }) => {
            assert.match(available_tools, /inputSchema/);
            return { name: "ticker_data", arguments: { symbol: "NVDA", dataset: "income_stmt" } };
        } },
    } });
    const reply = await agent.run("Compare Nvidia revenue", { stock_context: { recent_symbols: ["NVDA"] } });
    assert.equal(reply.usage.finance_data, 1);
    assert.equal(reply.usage.stock_history, undefined);
    assert.match(reply.answer, /get_income_stmt/);
});
