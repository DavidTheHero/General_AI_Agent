import test from "node:test";
import assert from "node:assert/strict";
import { AIMessage } from "@langchain/core/messages";
import { RunnableLambda } from "@langchain/core/runnables";
import { createAgent } from "../agent.js";
import { createChains, routingSchema } from "../llm.js";
import { SemanticMemoryStore, createMemory } from "../memory.js";

function fakeChains(outputs) {
    return Object.fromEntries(Object.entries(outputs).map(([name, output]) => [name, {
        invoke: async (input) => typeof output === "function" ? output(input) : output,
    }]));
}

test("LangChain prompt chains produce validated structured output", async () => {
    let prompt;
    const model = {
        withStructuredOutput(schema) {
            return RunnableLambda.from(async (input) => {
                prompt = input.toChatMessages();
                const message = new AIMessage('{"tool_choice":"calculator","calculator_expression":"12+18+20"}');
                return schema.parse(JSON.parse(message.content));
            });
        },
    };
    const result = await createChains(model).router.invoke({ query: "Add numbers", available_tools: "calculator" });
    assert.equal(result.tool_choice, "calculator");
    assert.match(prompt.at(-1).content, /Add numbers/);
    assert.equal(result.location, "");
});

test("calculator routing preserves response shape, profiling and semantic memory", async (t) => {
    const store = new SemanticMemoryStore(":memory:");
    t.after(() => store.close());
    const agent = createAgent({ store, chains: fakeChains({ router: { tool_choice: "calculator", calculator_expression: "12+18+20" } }) });
    const result = await agent.run("Add numbers", { session_id: "one", response_mode: "api" });
    assert.equal(result.answer, "12+18+20 = 50");
    assert.deepEqual(result.usage, { calculator: 1 });
    assert.equal(result.metadata.session_id, "one");
    assert.ok(result.timings.lm_router);
    assert.ok(store.query("one", "numbers").length);
    assert.deepEqual(Object.keys(result).sort(), ["answer", "responses", "usage", "token_usage", "metadata", "latency_ms", "timings", "model"].sort());
});

test("fallback and direct answers use the expected chains", async () => {
    const agent = createAgent({ chains: fakeChains({ router: { tool_choice: "none" }, general: { answer: "Hello!" } }) });
    assert.match((await agent.run("Hello")).answer, /Hello!/);
    const direct = createAgent({ chains: fakeChains({ router: { tool_choice: "none", direct_answer: "Direct" } }) });
    assert.equal((await direct.run("Hello", { response_mode: "api" })).answer, "Direct");
});

test("stock comparisons preserve plan traces, bounded history and follow-up context", async () => {
    const chains = fakeChains({ router: { tool_choice: "stock_quote", stock_symbol: "AAPL, MSFT" }, followup: { refers_to_stock_comparison: "No" } });
    const tools = { lookupSymbols: async () => ["AAPL", "MSFT"], stockHistory: async (symbol) => [{ close: 100 }, { close: symbol === "AAPL" ? 110 : 105 }] };
    const result = await createAgent({ chains, tools }).run("Compare AAPL with MSFT for 7 days");
    assert.match(result.answer, /AAPL outperformed MSFT/);
    assert.equal(result.metadata.plan_trace[0].outcome.best, "AAPL");
    assert.equal(result.metadata.user_profile.reminders.length, 1);
    const followup = createAgent({ chains: fakeChains({ router: { tool_choice: "none" }, followup: { refers_to_stock_comparison: "Yes" } }) });
    const next = await followup.run("Which performed better?", result.metadata);
    assert.match(next.answer, /5.00 percentage points/);
});

test("invalid routing and blank queries are rejected", async () => {
    assert.throws(() => routingSchema.parse({ tool_choice: "unknown" }));
    const agent = createAgent({ chains: fakeChains({ router: { tool_choice: "unknown" } }) });
    await assert.rejects(agent.run("Hello"));
    await assert.rejects(agent.run(" "), /cannot be empty/);
});

test("split queries preserve decimals and ticker suffixes", async () => {
    const queries = [];
    const agent = createAgent({ chains: fakeChains({ router: ({ query }) => { queries.push(query); return { tool_choice: "none", direct_answer: "OK" }; } }) });
    await agent.run("What is 1.5 plus 2? Tell me about BRK.B.");
    assert.deepEqual(queries, ["What is 1.5 plus 2", "Tell me about BRK.B"]);
});

test("concurrent requests keep memory and tool usage isolated", async () => {
    const agent = createAgent({ chains: fakeChains({ router: async ({ query }) => {
        await new Promise((resolve) => setTimeout(resolve, query === "First" ? 15 : 1));
        return { tool_choice: "none", direct_answer: query };
    } }) });
    const [a, b] = await Promise.all([agent.run("First", { session_id: "a" }), agent.run("Second", { session_id: "b" })]);
    assert.equal(a.metadata.session_id, "a");
    assert.equal(b.metadata.session_id, "b");
    assert.deepEqual(a.usage, { direct_response: 1 });
    assert.deepEqual(b.usage, { direct_response: 1 });
});

test("tool service failures are returned without crashing the query", async () => {
    const agent = createAgent({ chains: fakeChains({ router: { tool_choice: "weather", location: "London" } }), tools: { execute: async () => { throw new Error("Service unavailable"); } } });
    const result = await agent.run("Weather");
    assert.match(result.answer, /couldn’t reach the data service/);
    assert.match(result.answer, /try again/);
    assert.equal(result.metadata.tool_errors[0].message, "Service unavailable");
});

test("structured memory starts from isolated defaults", () => {
    const first = createMemory();
    first.stock_context.recent_symbols.push("AAPL");
    assert.deepEqual(createMemory().stock_context.recent_symbols, []);
});

test("stock clarification routing receives recent context even without semantic overlap", async (t) => {
    const store = new SemanticMemoryStore(":memory:");
    t.after(() => store.close());
    store.addEntry("stocks", "user", "how's the stock market today");
    store.addEntry("stocks", "assistant", "Specify at least one stock ticker or company name.");
    store.addEntry("other", "user", "Private unrelated conversation");
    let routedQuery;
    const tools = {
        lookupSymbols: async () => ["TTWO"],
        execute: async () => "TTWO: 200 USD",
    };
    const agent = createAgent({ store, tools, chains: fakeChains({ router: ({ query }) => {
        routedQuery = query;
        return { tool_choice: "stock_quote", stock_symbol: "TTWO" };
    } }) });
    assert.match((await agent.run("takes two interactive", { session_id: "stocks" })).answer, /TTWO/);
    assert.match(routedQuery, /how's the stock market today/);
    assert.match(routedQuery, /Specify at least one stock ticker/);
    assert.doesNotMatch(routedQuery, /Private unrelated/);
});


test("market overview and surprise me continue without requiring a ticker", async () => {
    const requests = [];
    const agent = createAgent({ chains: {}, tools: { execute: async (decision) => {
        requests.push(JSON.parse(decision.workspace_arguments));
        return { answer: "US benchmark snapshot", report: { workflow: "morning" } };
    } } });
    const first = await agent.run("How is the stock market today?", { response_mode: "api" });
    assert.equal(requests[0].workflow, "morning");
    assert.deepEqual(requests[0].watchlist, []);
    assert.equal(requests[0].timezone, "Europe/London");
    const next = await agent.run("surprise me", { ...first.metadata, response_mode: "api" });
    assert.equal(next.responses[0].query, "surprise me");
    assert.equal(next.responses[0].report.workflow, "morning");
    assert.equal(next.metadata.query_rewrites[0].original, "surprise me");
    assert.equal(requests.length, 2);
});

test("older market clarification conversations recover through session-scoped history", async (t) => {
    const store = new SemanticMemoryStore(":memory:"); t.after(() => store.close());
    store.addEntry("market", "user", "How is the stock market today?");
    store.addEntry("market", "assistant", "Specify at least one stock ticker or company name.");
    store.addEntry("other", "user", "Research my private portfolio");
    const agent = createAgent({ store, chains: {}, tools: { execute: async (decision) => {
        assert.equal(JSON.parse(decision.workspace_arguments).workflow, "morning");
        return "US benchmark snapshot";
    } } });
    assert.match((await agent.run("surprise me", { session_id: "market" })).answer, /US benchmark/);
});

test("context rewriting resolves references, preserves original input and ignores unrelated sessions", async (t) => {
    const store = new SemanticMemoryStore(":memory:"); t.after(() => store.close());
    store.addEntry("one", "user", "Weather in London");
    store.addEntry("two", "user", "Weather in Tokyo");
    let executed;
    const agent = createAgent({ store, chains: fakeChains({
        rewrite: (input) => {
            assert.match(input.conversation, /London/); assert.doesNotMatch(input.conversation, /Tokyo/);
            return { query: "What is the weather in London now", clarification: "" };
        }, router: { tool_choice: "weather", location: "London" },
    }), tools: { execute: async (_decision, query) => { executed = query; return "London observations"; } } });
    const result = await agent.run("what about there now?", { session_id: "one" });
    assert.equal(executed, "What is the weather in London now");
    assert.equal(result.responses[0].query, "what about there now");
    assert.ok(result.timings.lm_query_rewrite);
    assert.equal(store.recent("one").at(-2).content, "what about there now");
});

test("missing rewrite inputs clarify without tools and rewrite failures preserve the original", async () => {
    const metadata = { conversation_context: { last_effective_query: "Compare stocks" } };
    const clarify = createAgent({ chains: fakeChains({ rewrite: { query: "compare them", clarification: "Which two companies?" } }), tools: {} });
    assert.match((await clarify.run("compare them", metadata)).answer, /Which two companies/);
    const fallback = createAgent({ chains: fakeChains({ rewrite: () => { throw new Error("Model offline"); }, router: ({ query }) => {
        assert.equal(query, "what about that"); return { tool_choice: "none", direct_answer: "Which topic?" };
    } }) });
    assert.match((await fallback.run("what about that", metadata)).answer, /Which topic/);
});

test("tool outages offer continuation, retain diagnostics and allow retry", async () => {
    let calls = 0;
    const agent = createAgent({ chains: {}, tools: { execute: async () => {
        if (++calls === 1) throw new Error("fetch failed");
        return "US benchmark snapshot";
    } } });
    const failed = await agent.run("How is the stock market today?");
    assert.match(failed.answer, /try again/); assert.doesNotMatch(failed.answer, /fetch failed/);
    assert.equal(failed.metadata.tool_errors[0].message, "fetch failed");
    const recovered = await agent.run("try again", failed.metadata);
    assert.match(recovered.answer, /US benchmark snapshot/);
    assert.equal(recovered.metadata.tool_errors, undefined);
});

test("explicit topic changes and educational market questions are not rewritten into briefs", async () => {
    const agent = createAgent({ chains: fakeChains({ router: ({ query }) => ({ tool_choice: "none", direct_answer: query }) }) });
    const metadata = { conversation_context: { last_effective_query: "How is the stock market today" } };
    for (const query of ["Tell me a joke", "Explain how the stock market works", "How is the UK stock market today", "What time does the stock market open", "Market overview yesterday"]) {
        const result = await agent.run(query, metadata);
        assert.equal(result.responses[0].answer, query);
        assert.equal(result.metadata.query_rewrites, undefined);
    }
});
