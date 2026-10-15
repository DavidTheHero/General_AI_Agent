import test from "node:test";
import assert from "node:assert/strict";
import { runAgentLoop, loopObservation } from "../agent-loop.js";
import { createAgent } from "../agent.js";
import { SemanticMemoryStore } from "../memory.js";

const action = (tool, args = {}) => ({ action: "tool", tool, arguments: args });
const finish = (message) => ({ action: "finish", message });

test("empty search becomes evidence for an alternate search and verified report", async () => {
    const requested = [], report = { workflow: "research", data: { symbol: "FPT.VN" }, warnings: [] };
    const choices = [action("search", { query: "FPT" }), action("search", { query: "FPT Corporation" }), action("info", { symbol: "FPT.VN" }), action("report", { symbol: "FPT.VN" }), finish("FPT Corporation in Vietnam; financial report attached.")];
    const result = await runAgentLoop({ availableTools: new Set(["search", "info", "report"]), choose: async (observations) => {
        if (observations.length === 1) assert.deepEqual(observations[0].result.quotes, []);
        return choices.shift();
    }, execute: async (tool, args) => {
        requested.push([tool, args]);
        if (tool === "search") return { quotes: args.query === "FPT" ? [] : [{ symbol: "FPT.VN", name: "FPT Corporation" }] };
        if (tool === "info") return { country: "Vietnam", longName: "FPT Corporation" };
        return { answer: "Report generated", report };
    } });
    assert.equal(result.stop_reason, "complete"); assert.equal(result.report, report);
    assert.equal(requested.length, 4); assert.equal(result.trace.at(-1).action, "finish");
});

test("errors permit a different action but repeated identical arguments stop before execution", async () => {
    let calls = 0;
    const choices = [action("search", { country: "VN", query: "FPT" }), action("search", { query: "FPT", country: "VN" }), action("search", { query: "FPT", country: "VN" })];
    const result = await runAgentLoop({ availableTools: new Set(["search"]), choose: async (observations) => {
        if (observations.length) assert.equal(observations[0].error, "HTTP 403");
        return choices.shift();
    }, execute: async () => { calls++; throw new Error("HTTP 403"); } });
    assert.equal(calls, 1); assert.equal(result.stop_reason, "repeated_action");
});

test("unknown tools and failures are observations, never usable facts", async () => {
    const choices = [action("unknown"), finish("Invented current price is 100")];
    const result = await runAgentLoop({ availableTools: new Set(), choose: async () => choices.shift(), execute: async () => assert.fail("Unknown tools must not execute") });
    assert.equal(result.stop_reason, "no_evidence"); assert.doesNotMatch(result.answer, /100/);
});

test("step budget stops changing actions and still permits final synthesis at the limit", async () => {
    let i = 0, calls = 0;
    const result = await runAgentLoop({ maxSteps: 2, availableTools: new Set(["search"]), choose: async () => action("search", { query: String(i++) }), execute: async () => { calls++; return []; } });
    assert.equal(calls, 2); assert.equal(result.stop_reason, "step_limit");
    const complete = await runAgentLoop({ maxSteps: 1, availableTools: new Set(["search"]), seed: action("search"), choose: async () => finish("No matches; coverage remains unverified."), execute: async () => [] });
    assert.equal(complete.stop_reason, "complete");
});

test("planner failure and clarification stop cleanly without tools", async () => {
    for (const choice of [() => { throw new Error("Ollama offline"); }, () => ({ action: "clarify", message: "Which company do you mean?" })]) {
        const result = await runAgentLoop({ availableTools: new Set(), choose: choice, execute: async () => assert.fail() });
        assert.ok(["planner_error", "clarification"].includes(result.stop_reason));
    }
    const invalid = await runAgentLoop({ availableTools: new Set(), choose: async () => ({ action: "execute_code" }), execute: async () => assert.fail() });
    assert.equal(invalid.stop_reason, "planner_error");
});

test("observation previews are bounded and report sources are retained outside model context", () => {
    const result = loopObservation({ report: { workflow: "research", data: { text: "x".repeat(10000) }, sources: ["raw source"] } });
    assert.equal(result.truncated, true); assert.equal(result.preview.length, 2500);
});

test("default loop integration preserves MCP observations, report, usage and original history", async (t) => {
    const store = new SemanticMemoryStore(":memory:"); t.after(() => store.close());
    const report = { workflow: "research", source: "fixture", data: { symbol: "FPT.VN" }, warnings: [] };
    const choices = [action("mcp.search_stocks", { query: "FPT Corporation Vietnam" }), action("mcp.ticker_data", { symbol: "FPT.VN", dataset: "info" }), action("finance_workspace", { workflow: "research", symbol: "FPT.VN" }), finish("FPT Corporation research report attached.")];
    const agent = createAgent({ store, chains: { loop: { invoke: async (input) => {
        if (choices.length === 3) assert.match(input.observations, /FPT.VN/);
        return choices.shift();
    } } }, tools: {
        financeCatalog: async () => ["search_stocks", "ticker_data"].map((name) => ({ name, inputSchema: {} })),
        financeCall: async (name) => name === "search_stocks" ? { quotes: [{ symbol: "FPT.VN" }] } : { data: { country: "Vietnam", longName: "FPT Corporation" } },
        execute: async (decision) => { assert.equal(JSON.parse(decision.workspace_arguments).symbol, "FPT.VN"); return { answer: "Report", report }; },
    } });
    const result = await agent.run("brief about FPT a company in Vietnam", { session_id: "one", response_mode: "api" });
    assert.equal(result.responses[0].report, report); assert.equal(result.metadata.agent_trace[0].stop_reason, "complete");
    assert.equal(result.usage["mcp.search_stocks"], 1); assert.equal(result.token_usage.calls, 3);
    assert.equal(store.recent("one").at(-2).content, "brief about FPT a company in Vietnam");
    assert.deepEqual(store.recent("other"), []);
});

test("seeded market loop completes its report without another model call", async () => {
    const agent = createAgent({ chains: { loop: { invoke: async (input) => {
        assert.fail("A ready market brief should complete without another model call");
    } } }, tools: { execute: async (decision) => ({ answer: "Report", report: { workflow: JSON.parse(decision.workspace_arguments).workflow, data: {}, warnings: [] } }) } });
    const result = await agent.run("How is the stock market today?");
    assert.equal(result.responses[0].report.workflow, "morning");
    assert.equal(result.metadata.agent_trace[0].steps[0].tool, "finance_workspace");
    assert.equal(result.token_usage.calls, 0);
    assert.equal(result.metadata.agent_trace[0].steps.at(-1).completion, "report_ready");
});


test("research reports cannot bypass company metadata inspection", async () => {
    const choices = [action("finance_workspace", { workflow: "research", symbol: "FPT" }), { action: "clarify", message: "Please confirm the listing." }];
    let executed = false;
    const agent = createAgent({ chains: { loop: { invoke: async (input) => {
        if (choices.length === 1) assert.match(input.observations, /identity has not been inspected/);
        return choices.shift();
    } } }, tools: { execute: async () => { executed = true; } } });
    const result = await agent.run("brief about FPT a company in Vietnam");
    assert.equal(executed, false); assert.equal(result.metadata.agent_trace[0].stop_reason, "clarification");
});

test("a failed tool can be followed by a different successful tool", async () => {
    const choices = [action("search"), action("lookup"), finish("The alternate lookup found FPT.VN; identity still needs verification.")];
    const result = await runAgentLoop({ availableTools: new Set(["search", "lookup"]), choose: async () => choices.shift(), execute: async (name) => {
        if (name === "search") throw new Error("Search unavailable");
        return { symbol: "FPT.VN" };
    } });
    assert.equal(result.stop_reason, "complete");
    assert.deepEqual(result.observations.map((item) => item.status), ["error", "ok"]);
});

test("concurrent loops do not share observations or repeat detection", async () => {
    const run = (symbol) => runAgentLoop({ availableTools: new Set(["lookup"]), choose: async (observations) => observations.length ? finish(observations[0].result.symbol) : action("lookup", { symbol }), execute: async (_name, args) => args });
    const [a, b] = await Promise.all([run("FPT.VN"), run("NVDA")]);
    assert.equal(a.answer, "FPT.VN"); assert.equal(b.answer, "NVDA");
    assert.equal(a.observations.length, 1); assert.equal(b.observations.length, 1);
});


test("one blocked repeat gives the planner feedback to recover without repeating execution", async () => {
    const choices = [action("lookup"), action("lookup"), finish("Use the existing lookup evidence.")];
    let calls = 0;
    const result = await runAgentLoop({ availableTools: new Set(["lookup"]), choose: async () => choices.shift(), execute: async () => { calls++; return { name: "FPT" }; } });
    assert.equal(calls, 1); assert.equal(result.stop_reason, "complete");
    assert.equal(result.trace[1].status, "blocked_repeat");
});

test("MCP quotes retain session context for later currency conversion", async () => {
    const choices = [action("mcp.stock_quote", { symbol: "NVDA" }), finish("NVDA quote retrieved.")];
    const quote = { symbol: "NVDA", price: 100, currency: "USD", date: "2026-10-15" };
    const agent = createAgent({ chains: { loop: { invoke: async () => choices.shift() } }, tools: {
        financeCatalog: async () => [{ name: "stock_quote", inputSchema: {} }], financeCall: async () => quote,
    } });
    const result = await agent.run("Nvidia stock price");
    assert.deepEqual(result.metadata.stock_context.last_quote, quote);
    assert.deepEqual(result.metadata.stock_context.recent_symbols, ["NVDA"]);
});

test("empty company discovery cannot validate an acronym and allows a fuller-name search", async () => {
    const choices = [action("mcp.search_stocks", { query: "FPT Vietnam" }), action("mcp.ticker_data", { symbol: "FPT", dataset: "info" }), action("mcp.search_stocks", { query: "FPT Corporation" }), action("mcp.ticker_data", { symbol: "FPT.VN", dataset: "info" }), action("finance_workspace", { workflow: "research", symbol: "FPT.VN" }), finish("FPT Corporation report attached.")];
    const fetched = [];
    const agent = createAgent({ chains: { loop: { invoke: async (input) => {
        if (choices.length === 5) assert.ok(!input.allowed_tools.includes("mcp.ticker_data"));
        if (choices.length === 3) assert.ok(input.allowed_tools.includes("mcp.ticker_data"));
        if (choices.length === 2) assert.ok(!input.allowed_tools.includes("mcp.ticker_data"));
        return choices.shift();
    } } }, tools: {
        financeCatalog: async () => ["search_stocks", "ticker_data"].map((name) => ({ name, inputSchema: {} })),
        financeCall: async (name, args) => {
            fetched.push(args);
            return name === "search_stocks" ? { quotes: args.query === "FPT Vietnam" ? [] : [{ symbol: "FPT.VN", name: "FPT Corporation" }] } : { data: { longName: "FPT Corporation", country: "Vietnam" } };
        }, execute: async () => ({ answer: "Report", report: { workflow: "research", data: {}, warnings: [] } }),
    } });
    const result = await agent.run("brief about FPT a company in Vietnam");
    assert.equal(result.metadata.agent_trace[0].stop_reason, "complete");
    assert.equal(fetched.some((args) => args.symbol === "FPT"), false);
    assert.equal(fetched.some((args) => args.symbol === "FPT.VN"), true);
    assert.match(result.metadata.tool_errors[0].message, /not returned by company discovery/);
});


test("explicit report goals stop on a ready report and never claim completion without one", async () => {
    const report = { workflow: "research", data: {}, warnings: [] };
    const complete = await runAgentLoop({ availableTools: new Set(["report"]), seed: action("report"), finishOnReport: true, requireReport: true,
        choose: async () => assert.fail("Report is already complete"), execute: async () => ({ answer: "Verified report attached.", report }) });
    assert.equal(complete.stop_reason, "complete"); assert.equal(complete.report, report);
    const incomplete = await runAgentLoop({ availableTools: new Set(), requireReport: true, choose: async () => finish("An invented company report"), execute: async () => assert.fail() });
    assert.equal(incomplete.stop_reason, "incomplete"); assert.doesNotMatch(incomplete.answer, /invented/);
});
