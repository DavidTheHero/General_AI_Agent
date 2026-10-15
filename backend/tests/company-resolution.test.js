import test from "node:test";
import assert from "node:assert/strict";
import { createCompanyResolver } from "../finance/resolve-company.js";
import { createAgent } from "../agent.js";
import { createChains } from "../llm.js";
import { RunnableLambda } from "@langchain/core/runnables";

const info = (symbol, country = "Vietnam", name = "FPT Corporation") => ({ source: "fixture", retrieved_at: "2026-10-15", data: { symbol, longName: name, country, currency: "VND" } });

test("FPT identity retains the country separately from the provider search query", async () => {
    const calls = [];
    const resolve = createCompanyResolver({ call: async (name, args) => {
        calls.push([name, args]);
        return name === "search_stocks" ? { quotes: [{ symbol: "FPT.VN", name: "FPT Corporation" }, { symbol: "FPT.BK", name: "FPT Frasers Property" }] } : info(args.symbol, args.symbol.endsWith(".VN") ? "Viet Nam" : "Thailand", args.symbol.endsWith(".VN") ? "FPT Corporation" : "FPT Frasers Property");
    } });
    const result = await resolve({ name: "FPT", country: "Vietnam" });
    assert.equal(result.status, "resolved"); assert.equal(result.company.symbol, "FPT.VN");
    assert.equal(calls[0][1].query, "FPT"); assert.equal(result.unverified_candidates[0].reason, "Country differs");
});

test("empty search falls back to stock lookup and verifies actual listing metadata", async () => {
    const calls = [];
    const resolve = createCompanyResolver({ call: async (name, args) => {
        calls.push(name);
        if (name === "search_stocks") return { quotes: [] };
        if (name === "lookup_instruments") { assert.equal(args.category, "stock"); return { data: { columns: ["shortName", "exchange"], index: ["FPT.VN"], rows: [["FPT Corporation", "VSE"]] } }; }
        return info("FPT.VN");
    } });
    const result = await resolve({ name: "FPT", country: "Vietnam" });
    assert.equal(result.status, "resolved"); assert.deepEqual(calls, ["search_stocks", "lookup_instruments", "ticker_data"]);
});

test("full-name expansion is bounded and no matches do not imply absent coverage", async () => {
    const calls = [];
    const resolve = createCompanyResolver({ call: async (name, args) => { calls.push(args); return name === "search_stocks" ? { quotes: [] } : { data: null }; } });
    const result = await resolve({ name: "FPT", country: "Vietnam" });
    assert.equal(result.status, "not_found"); assert.equal(calls.length, 3); assert.equal(calls[2].query, "FPT Corporation");
});

test("country mismatch, missing identity and provider symbol mismatch cannot resolve a company", async () => {
    for (const profile of [info("FPT.VN", "Thailand"), { data: { longName: "FPT Corporation" } }, info("WRONG.VN")]) {
        const resolve = createCompanyResolver({ call: async (name) => name === "search_stocks" ? { quotes: [{ symbol: "FPT.VN", name: "FPT Corporation" }] } : profile });
        const result = await resolve({ name: "FPT", country: "Vietnam" });
        assert.equal(result.status, "not_found"); assert.equal(result.company, undefined);
    }
});

test("ambiguous listings require a choice and explicit suffixed tickers resolve", async () => {
    const resolve = createCompanyResolver({ call: async (name, args) => name === "search_stocks" ? { quotes: (args.query === "FPT.VN" ? ["FPT.VN"] : ["FPT.VN", "FPT.A"]).map((symbol) => ({ symbol, name: "FPT Corporation" })) } : info(args.symbol) });
    assert.equal((await resolve({ name: "FPT", country: "Vietnam" })).status, "ambiguous");
    assert.equal((await resolve({ name: "FPT.VN", country: "Vietnam" })).company.symbol, "FPT.VN");
});

test("inspection budgets do not imply uniqueness among uninspected equal candidates", async () => {
    let inspected = 0;
    const resolve = createCompanyResolver({ call: async (name, args) => {
        if (name === "search_stocks") return { quotes: ["FPT.VN", "FPT.A", "FPT.B", "FPT.C"].map((symbol) => ({ symbol, name: "FPT Corporation" })) };
        inspected++; return info(args.symbol, args.symbol === "FPT.VN" ? "Vietnam" : "Thailand");
    } });
    const result = await resolve({ name: "FPT", country: "Vietnam" });
    assert.equal(inspected, 3); assert.equal(result.status, "ambiguous"); assert.ok(result.limitation);
});

test("provider failures are distinct from empty results and invalid input never reaches providers", async () => {
    const resolve = createCompanyResolver({ call: async () => { throw new Error("Yahoo unavailable"); } });
    const result = await resolve({ name: "FPT", country: "Vietnam" });
    assert.equal(result.status, "unavailable"); assert.equal(result.errors.length, 3);
    await assert.rejects(resolve({ name: "" }));
});

test("loop schema constrains tool names to the choices exposed at the current step", async () => {
    let choices;
    const chains = createChains({ withStructuredOutput: (schema) => {
        if (schema.shape?.tool) choices = schema.shape.tool.unwrap().options;
        return RunnableLambda.from(async () => ({ action: "clarify", tool: "", arguments: {}, message: "Which listing?" }));
    } });
    await chains.loop.invoke({ allowed_tools: ["resolve_company"], query: "FPT brief", context: "", reference_date: "2026-10-15", timezone: "Europe/London", available_tools: "", observations: "[]", remaining_steps: 6 });
    assert.deepEqual(choices, ["", "resolve_company"]);
});

test("company loop transitions from resolver to report and records nested MCP actions", async () => {
    const report = { workflow: "research", source: "fixture", data: {}, warnings: [] };
    const choices = [{ action: "tool", tool: "resolve_company", arguments: { name: "FPT", country: "Vietnam" } }, { action: "tool", tool: "finance_workspace", arguments: { workflow: "research", symbol: "FPT.VN" } }, { action: "finish", message: "FPT Corporation research report attached." }];
    const agent = createAgent({ chains: { loop: { invoke: async (input) => {
        assert.deepEqual(input.allowed_tools, choices.length === 3 ? ["resolve_company"] : choices.length === 2 ? ["finance_workspace"] : []);
        return choices.shift();
    } } }, tools: {
        resolveCompany: createCompanyResolver({ call: async (name, args) => name === "search_stocks" ? { quotes: [{ symbol: "FPT.VN", name: "FPT Corporation" }] } : info(args.symbol) }),
        execute: async (decision) => { assert.equal(JSON.parse(decision.workspace_arguments).symbol, "FPT.VN"); return { answer: "Report", report }; },
    } });
    const result = await agent.run("brief about FPT a company in Vietnam");
    assert.equal(result.metadata.agent_trace[0].stop_reason, "complete");
    assert.equal(result.metadata.agent_trace[0].steps[0].attempts.length, 2);
    assert.equal(result.responses[0].report, report);
});
