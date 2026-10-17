import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { calculate } from "../calculator.js";
import { createTools, currentTime, convertTime, extractSymbols, extractDays } from "../tools.js";
import { createMemory, SemanticMemoryStore, rememberComparison } from "../memory.js";

test("arithmetic supports precedence, unary signs and Python-style operators", () => {
    for (const [input, expected] of [["12+18+20", 50], ["(2+3)*4", 20], ["2**3**2", 512], ["-2**2", -4], ["2**-2", .25], ["-7//2", -4], ["-7%2", 1], ["1.5+2", 3.5]]) assert.equal(calculate(input), expected);
    for (const input of ["process.exit()", "1/0", "", "2a", "(2", "Infinity", "2**9999"]) assert.throws(() => calculate(input));
});

test("timezone conversion handles DST and explicit offsets", () => {
    const result = convertTime("2026-07-01T12:00:00", "Europe/London", "America/New_York");
    assert.match(result.converted_time, /07:00:00.*-04:00/);
    assert.match(convertTime("2026-07-01T12:00:00Z", "Europe/London", "UTC").converted_time, /12:00:00/);
    assert.equal(currentTime("Europe/London").timezone, "Europe/London");
    assert.throws(() => currentTime("Invalid/Zone"));
    assert.throws(() => convertTime("bad date"));
});

test("stock helpers call finance MCP and preserve prices and context", async () => {
    assert.deepEqual(extractSymbols("AAPL", "Compare Tesla and Microsoft"), ["TSLA", "MSFT", "AAPL"]);
    assert.equal(extractDays("for 2 weeks"), 14);
    assert.deepEqual(extractSymbols("", "takes two interactive"), ["TTWO"]);
    const calls = [];
    const tools = createTools(async () => { throw new Error("Direct finance HTTP must not be used"); }, {
        call: async (name, args) => {
            calls.push({ name, args });
            if (name === "stock_history") return { currency: "USD", history: [{ close: 115 }] };
            if (name === "stock_quote") return { symbol: "AAPL", price: 115, currency: "USD", change: 10, percent_change: 9.52, source: "Yahoo Finance via yfinance", date: "2026-01-02" };
            return { quotes: [{ symbol: "TTWO" }] };
        },
    });
    assert.deepEqual((await tools.stockHistory("AAPL", 1)).map((row) => row.close), [115]);
    const memory = createMemory();
    assert.match(await tools.execute({ tool_choice: "stock_quote", stock_symbol: "AAPL" }, "AAPL", memory), /115.00 USD/);
    assert.deepEqual(memory.stock_context.recent_symbols, ["AAPL"]);
    assert.deepEqual(await tools.lookupSymbols("", "unknown company"), ["TTWO"]);
    assert.deepEqual(calls.map((call) => call.name), ["stock_history", "stock_quote", "search_stocks"]);
});

test("finance MCP failures are surfaced without direct HTTP fallback", async () => {
    const tools = createTools(fetch, { call: async () => { throw new Error("Finance MCP: provider returned HTTP 403"); } });
    await assert.rejects(tools.stockHistory("TTWO"), /Finance MCP.*403/);
});

test("weather updates structured context using mocked service data", async () => {
    const tools = createTools(async (url) => Response.json(url.hostname.startsWith("geocoding") ? { results: [{ name: "London", country: "UK", latitude: 51, longitude: 0, timezone: "Europe/London" }] } : { current_weather: { temperature: 12, windspeed: 10 } }));
    const memory = createMemory();
    assert.match(await tools.execute({ tool_choice: "weather", location: "London" }, "Weather", memory), /12°C in London/);
    assert.equal(memory.weather_context.last_location.name, "London");
});

test("each remote tool handles its service payload", async () => {
    const payloads = {
        topic_summary: { title: "Paris", extract: "City", content_urls: { desktop: { page: "https://example.com" } } },
        news: { hits: [{ title: "News", url: "https://example.com" }] },
        news_api: { data: { children: [{ data: { title: "Post", subreddit: "news", url: "https://example.com" } }] } },
        crypto_price: { bitcoin: { usd: 100 } },
        holiday_lookup: [{ date: "2099-12-25", localName: "Christmas", types: ["Public"] }],
        fun_activity: { activity: "Read", type: "relaxation", participants: 1 },
        fun_joke: { type: "single", joke: "Joke", category: "Misc" },
        fact_lookup: { AbstractText: "Fact", AbstractSource: "Source", AbstractURL: "https://example.com" },
    };
    for (const [tool_choice, payload] of Object.entries(payloads)) {
        const tools = createTools(async () => Response.json(payload));
        const result = await tools.execute({ tool_choice, topic: "Paris", news_query: "News", crypto_asset: "bitcoin", holiday_year: "2099" }, "Question", createMemory(), async () => "Refined fact");
        assert.equal(typeof result, "string", tool_choice);
        assert.ok(result.length, tool_choice);
    }
});

test("empty holiday results do not throw and HTTP failures surface", async () => {
    const tools = createTools(async () => Response.json([]));
    assert.equal(await tools.execute({ tool_choice: "holiday_lookup" }, "holidays", createMemory()), "No upcoming holidays found.");
    const failed = createTools(async () => new Response("", { status: 503 }));
    await assert.rejects(failed.execute({ tool_choice: "news", news_query: "News" }, "News", createMemory()), /503/);
});

test("comparison history is bounded", () => {
    const memory = createMemory();
    for (let i = 0; i < 12; i++) rememberComparison(memory, [{ symbol: `S${i}`, start: 1, end: 2, change_pct: 100 }], 7);
    assert.equal(memory.stock_context.comparison_history.length, 5);
    assert.equal(memory.stock_context.recent_symbols.length, 8);
});

test("semantic memory persists across restarts and supports legacy embeddings", (t) => {
    const directory = mkdtempSync(join(tmpdir(), "agent-memory-"));
    const path = join(directory, "memory.db");
    const first = new SemanticMemoryStore(path);
    first.addEntry("one", "user", "Visiting Paris in summer");
    first.db.prepare("UPDATE semantic_memory SET embedding = ?").run("[0,0]");
    first.close();
    const second = new SemanticMemoryStore(path);
    t.after(() => {
        second.close();
        rmSync(directory, { recursive: true });
    });
    assert.ok(second.query("one", "Paris trip").length);
    assert.equal(second.query("other", "Paris trip").length, 0);
});
