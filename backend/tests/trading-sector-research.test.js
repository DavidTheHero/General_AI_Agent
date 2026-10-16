import test from "node:test";
import assert from "node:assert/strict";
import request from "supertest";
import { createApp } from "../app.js";
import { tradingDescriptions, tradingInputs } from "../trading/client.js";
import { createAgent } from "../agent.js";
import { loopObservation } from "../agent-loop.js";

const id = "a".repeat(32);

test("sector research routes preserve the frozen protocol and scope status/list", async () => {
    const calls = [];
    const fixture = { id, status: "running", simulation_only: true, request: { mode: "sector_research" } };
    const app = createApp({ frontendPath: "/nonexistent", trading: { call: async (...args) => {
        calls.push(args);
        return args[0] === "trading_list" ? { jobs: [fixture, { id: "b".repeat(32), request: { mode: "daily_research" } }] } : fixture;
    } } });
    const research = { development_end: "2022-12-30", reserved_final_start: "2023-01-03", reserved_final_end: "2025-12-31", cost_bps: [5, 10, 20] };
    await request(app).post("/trading/sector-research").send(research).expect(202, fixture);
    assert.deepEqual(calls.at(-1), ["trading_sector_research_start", { research }]);
    await request(app).get(`/trading/sector-research/${id}`).expect(200, fixture);
    assert.deepEqual(calls.at(-1), ["trading_sector_research_status", { job_id: id }]);
    const listed = await request(app).get("/trading/sector-research").expect(200);
    assert.deepEqual(listed.body.jobs.map((job) => job.id), [id]);
    const before = calls.length;
    await request(app).get("/trading/sector-research/invalid").expect(400);
    for (const invalid of [{ cost_bps: [5] }, { development_end: "2023-12-29" }, { finalize: true }, { top_k: 2 }]) {
        await request(app).post("/trading/sector-research").send(invalid).expect(400);
    }
    assert.equal(calls.length, before);
});

test("sector discovery freezes the hypothesis and keeps final prices reserved", () => {
    assert.match(tradingDescriptions.trading_sector_research_start, /exactly four configurations/);
    assert.match(tradingDescriptions.trading_sector_research_start, /without acquiring or evaluating/);
    assert.match(tradingDescriptions.trading_sector_research_start, /not a validated strategy/);
    assert.deepEqual(tradingInputs.trading_sector_research_start.parse({ research: {} }), { research: {} });
    const universe = ["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY", "SPY"];
    assert.deepEqual(tradingInputs.trading_sector_research_start.parse({ research: { symbols: universe, initial_cash: 100000, cost_bps: [5, 10, 20] } }).research.symbols, universe);
    for (const research of [{ source: "synthetic" }, { lookbacks: [126] }, { top_k: [1, 3] },
        { cost_bps: [5] }, { cost_bps: [5, 10, 30] }, { symbols: universe.toReversed() },
        { data_start: "2001-01-02" }, { development_start: "2002-01-02" }, { validation_start: "2014-01-02" },
        { development_end: "2023-12-29" }, { reserved_final_start: "2024-01-02" }, { reserved_final_end: "2026-01-02" },
        { initial_cash: 99999 }, { interval: "1d" }]) {
        assert.throws(() => tradingInputs.trading_sector_research_start.parse({ research }));
    }
});

test("sector research agent submits once and retains a bounded receipt", async () => {
    let calls = 0, steps = 0;
    const fixture = { id, status: "running", simulation_only: true, dashboard_url: `/?trading_job=${id}` };
    const agent = createAgent({ tools: {}, trading: { call: async (name, args) => {
        calls++;
        assert.equal(name, "trading_sector_research_start");
        assert.deepEqual(args, { research: {} });
        return fixture;
    } }, chains: { loop: { invoke: async (input) => {
        if (steps++ === 0) {
            assert.ok(input.allowed_tools.includes("trading_sector_research_start"));
            return { action: "tool", tool: "trading_sector_research_start", arguments: { research: {} } };
        }
        assert.deepEqual(input.allowed_tools, []);
        return { action: "finish", message: "Frozen sector research started; results remain exploratory." };
    } } } });
    const reply = await agent.run("Run the frozen sector momentum research study");
    assert.equal(calls, 1);
    assert.equal(reply.metadata.conversation_context.last_trading_job_id, id);
    assert.equal(reply.responses[0].trading_job.id, id);
    const compact = loopObservation({ id, status: "complete", daily_research: {
        assessment: "inconclusive", promotion_status: "research_only", reserved_final: { accessed: false },
        provenance_ref: "sector-studies/fixture/dataset/manifest.json", attempts: Array(100).fill({ rows: "x".repeat(10000) }),
    } }, "trading_sector_research_status");
    assert.equal(compact.daily_research.reserved_final.accessed, false);
    assert.equal(compact.daily_research.attempts, undefined);
    assert.ok(JSON.stringify(compact).length < 1200);
});
