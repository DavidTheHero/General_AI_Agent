import test from "node:test";
import assert from "node:assert/strict";
import { createTools, quoteConversionTarget } from "../tools.js";
import { createMemory } from "../memory.js";
import { createAgent } from "../agent.js";

test("NVDA quote follow-up converts the saved price rather than looking up GBP", async () => {
    const calls = [];
    const tools = createTools(fetch, { call: async (name, args) => {
        calls.push({ name, args });
        if (name === "stock_quote") return { symbol: "NVDA", price: 221.30, currency: "USD", change: -7.22, percent_change: -3.16, date: "2026-10-14", source: "Yahoo Finance via yfinance" };
        assert.equal(name, "exchange_rate");
        assert.deepEqual(args, { from_currency: "USD", to_currency: "GBP" });
        return { rate: .75, date: "2026-10-13", source: "Yahoo Finance via yfinance" };
    } });
    const agent = createAgent({ tools, chains: { router: { invoke: async () => ({ tool_choice: "stock_quote", stock_symbol: "NVDA" }) } } });
    const quote = await agent.run("nvidia stock price today");
    const conversion = await agent.run("can you change that to GBP", quote.metadata);
    assert.match(conversion.answer, /£165.98 GBP/);
    assert.match(conversion.answer, /Stock data as of 2026-10-14/);
    assert.match(conversion.answer, /FX rate.*as of 2026-10-13/);
    assert.deepEqual(calls.map(({ name }) => name), ["stock_quote", "exchange_rate"]);
});

test("missing context and same-currency requests do not call a provider", async () => {
    const tools = createTools(fetch, { call: async () => { throw new Error("Unexpected provider call"); } });
    const memory = createMemory();
    assert.match(await tools.execute({ tool_choice: "currency_convert", target_currency: "GBP" }, "", memory), /request a stock quote first/);
    memory.stock_context.last_quote = { symbol: "NVDA", price: 100, currency: "GBP", date: "2026-10-14" };
    assert.match(await tools.execute({ tool_choice: "currency_convert", target_currency: "GBP" }, "", memory), /already in GBP/);
    memory.stock_context.last_quote.currency = "GBp";
    assert.match(await tools.execute({ tool_choice: "currency_convert", target_currency: "GBP" }, "", memory), /£1.00 GBP/);
});

test("conversion failure preserves the original quote", async () => {
    const tools = createTools(fetch, { call: async () => { throw new Error("FX unavailable"); } });
    const memory = createMemory({ stock_context: { last_quote: { symbol: "NVDA", price: 100, currency: "USD", date: "2026-10-14" } } });
    await assert.rejects(tools.execute({ tool_choice: "currency_convert", target_currency: "GBP" }, "", memory), /FX unavailable/);
    assert.equal(memory.stock_context.last_quote.price, 100);
    assert.equal(memory.stock_context.last_quote.currency, "USD");
    assert.equal(quoteConversionTarget("convert time to UTC"), null);
    assert.equal(quoteConversionTarget("show Microsoft stock price in GBP"), null);
    assert.equal(createMemory().stock_context.last_quote, null);
});
