import test from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { FinanceMcpClient } from "../finance/client.js";
import { createTools } from "../tools.js";
import { createAgent } from "../agent.js";

const fixture = fileURLToPath(new URL("../finance/tests/fixture_server.py", import.meta.url));

test("real MCP discovery, tool calls and agent integration work offline", async (t) => {
    const client = new FinanceMcpClient({ args: [fixture] });
    t.after(() => client.close());
    await client.connect();
    assert.equal(client.tools.length, 18);
    assert.ok(client.tools.some((tool) => tool.name === "ticker_data"));
    assert.ok(client.tools.every((tool) => tool.inputSchema.type === "object"));
    const search = await client.call("search_stocks", { query: "Take Two" });
    assert.equal(search.quotes[0].symbol, "TTWO");
    const quote = await client.call("stock_quote", { symbol: "TTWO" });
    assert.equal(quote.price, 115);
    assert.equal(quote.change, 10);
    assert.equal(quote.adjusted, false);
    const history = await client.call("stock_history", { symbol: "TTWO", days: 1 });
    assert.equal(history.history.length, 1);
    assert.equal(history.history[0].close, 115);
    const tools = createTools(async () => { throw new Error("No external HTTP in protocol tests"); }, client);
    const agent = createAgent({ tools, chains: { router: { invoke: async () => ({ tool_choice: "stock_quote", stock_symbol: "TTWO" }) } } });
    const reply = await agent.run("Take-Two stock");
    assert.match(reply.answer, /TTWO: 115.00 USD/);
    assert.equal(reply.usage.stock_quote, 1);
    const converted = await agent.run("can you change that to GBP", reply.metadata);
    assert.match(converted.answer, /£86.25 GBP/);
    assert.equal(converted.usage.currency_convert, 1);
    assert.equal(converted.usage.stock_history, undefined);
    assert.equal(converted.metadata.stock_context.last_quote.currency, "USD");
    assert.match(converted.answer, /Stock data as of 2026-01-02; FX rate 0.75.*as of 2026-01-02/);
    await assert.rejects(client.call("exchange_rate", { from_currency: "USD", to_currency: "GBP;" }), /currency codes/);
    await assert.rejects(client.call("stock_history", { symbol: "TTWO", days: 0 }));
    await assert.rejects(client.call("stock_quote", { symbol: "EMPTY" }), /No historical data/);
    await assert.rejects(client.call("stock_quote", { symbol: "FAIL" }), /Yahoo unavailable/);
    await assert.rejects(client.call("stock_quote", { symbol: "bad;command" }), /valid Yahoo Finance/);
    await assert.rejects(client.call("search_stocks", { query: " " }), /blank/);
    assert.equal((await client.call("stock_quote", { symbol: "TTWO" })).price, 115);
    await client.close();
    assert.equal(client.client, null);
});

test("MCP client reports startup errors and rejects unknown tools", async () => {
    const client = new FinanceMcpClient({ command: "/does-not-exist/python", timeout: 1000 });
    await assert.rejects(client.call("stock_quote", { symbol: "TTWO" }), /could not start/);
    await assert.rejects(client.call("delete_everything", {}), /Unsupported finance tool/);
    await client.close();
});

test("MCP timeouts close the subprocess and subsequent calls reconnect", async (t) => {
    const client = new FinanceMcpClient({ args: [fixture] });
    t.after(() => client.close());
    await client.connect();
    client.timeout = 50;
    await assert.rejects(client.call("stock_quote", { symbol: "SLOW" }), /timed out/);
    assert.equal(client.client, null);
    client.timeout = 30000;
    assert.equal((await client.call("stock_quote", { symbol: "TTWO" })).price, 115);
});
