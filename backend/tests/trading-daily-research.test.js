import test from "node:test";
import assert from "node:assert/strict";
import request from "supertest";
import { createApp } from "../app.js";
import { tradingDescriptions, tradingInputs } from "../trading/client.js";
import { createAgent } from "../agent.js";
import { loopObservation } from "../agent-loop.js";

const id = "a".repeat(32);

test("daily research routes preserve requested dates and expose scoped status", async () => {
    const calls = [];
    const fixture = { id, status: "running", simulation_only: true, request: { mode: "daily_research" } };
    const app = createApp({ frontendPath: "/nonexistent", trading: { call: async (...args) => {
        calls.push(args);
        return args[0] === "trading_list" ? { jobs: [fixture, { id: "b".repeat(32), request: { mode: "demo" } }] } : fixture;
    } } });
    const research = { symbols: ["SPY", "IEF", "GLD"], development_end: "2022-12-30", reserved_final_start: "2023-01-03", reserved_final_end: "2025-12-31", lookbacks: [126, 252], cost_bps: [5, 20] };
    await request(app).post("/trading/daily-research").send(research).expect(202, fixture);
    assert.deepEqual(calls.at(-1), ["trading_daily_research_start", { research }]);
    await request(app).get(`/trading/daily-research/${id}`).expect(200, fixture);
    assert.deepEqual(calls.at(-1), ["trading_daily_research_status", { job_id: id }]);
    const listed = await request(app).get("/trading/daily-research").expect(200);
    assert.deepEqual(listed.body.jobs.map((job) => job.id), [id]);
    const before = calls.length;
    await request(app).get("/trading/daily-research/../token").expect(404);
    await request(app).get("/trading/daily-research/invalid").expect(400);
    await request(app).post("/trading/daily-research").send({ symbols: ["SPY", "QQQ", "IEF", "GLD"] }).expect(400);
    await request(app).post("/trading/daily-research").send({ finalize: true }).expect(400);
    assert.equal(calls.length, before);
});

test("daily discovery describes exploratory proxy evidence and strictly bounded inputs", () => {
    assert.match(tradingDescriptions.trading_daily_research_start, /total-return proxies/);
    assert.match(tradingDescriptions.trading_daily_research_start, /not a validated strategy/);
    assert.deepEqual(tradingInputs.trading_daily_research_start.parse({ research: {} }), { research: {} });
    for (const research of [{ source: "synthetic" }, { lookbacks: [0] }, { lookbacks: [126, 189, 252, 300] },
        { cost_bps: [-1] }, { symbols: ["spy"] }, { symbols: ["SPY"] }, { symbols: ["GLD", "SPY", "IEF"] }, { interval: "1m" }]) {
        assert.throws(() => tradingInputs.trading_daily_research_start.parse({ research }));
    }
});

test("daily research agent submits one job and retains its returned ID", async () => {
    let calls = 0, steps = 0;
    const fixture = { id, status: "running", simulation_only: true, dashboard_url: `/?trading_job=${id}` };
    const agent = createAgent({ tools: {}, trading: { call: async (name, args) => {
        calls++;
        assert.equal(name, "trading_daily_research_start");
        assert.deepEqual(args, { research: {} });
        return fixture;
    } }, chains: { loop: { invoke: async (input) => {
        if (steps++ === 0) {
            assert.ok(input.allowed_tools.includes("trading_daily_research_start"));
            return { action: "tool", tool: "trading_daily_research_start", arguments: { research: {} } };
        }
        assert.deepEqual(input.allowed_tools, []);
        assert.equal(JSON.parse(input.observations)[0].result.id, id);
        return { action: "finish", message: "Daily exploratory research started; no profitable edge has been established." };
    } } } });
    const reply = await agent.run("Run the registered daily ETF edge research pilot");
    assert.equal(calls, 1);
    assert.equal(reply.metadata.conversation_context.last_trading_job_id, id);
    assert.equal(reply.responses[0].trading_job.id, id);
    assert.equal(reply.usage.trading_daily_research_start, 1);
});

test("daily status observations retain assessment and holdout guard without full ledgers", () => {
    const compact = loopObservation({ id, status: "complete", daily_research: {
        experiment_id: id, assessment: "inconclusive", promotion_status: "research_only", metrics: { attempts: 32 },
        reserved_final: { start: "2023-01-03", end: "2025-12-31", accessed: false },
        promotion_blockers: ["No independent replication", "No forward paper observations"],
        provenance_ref: "daily-studies/fixture/dataset/manifest.json",
        attempts: Array(160).fill({ rows: "x".repeat(10000) }), comparisons: Array(100).fill({ rows: "x".repeat(1000) }),
        environment: { raw: "x".repeat(10000) },
    }, progress: { attempts_completed: 32, state: "daily_research" } }, "trading_daily_research_status");
    assert.equal(compact.daily_research.assessment, "inconclusive");
    assert.equal(compact.daily_research.promotion_status, "research_only");
    assert.equal(compact.daily_research.reserved_final.accessed, false);
    assert.equal(compact.daily_research.promotion_blockers.length, 2);
    assert.equal(compact.progress.attempts_completed, 32);
    assert.equal(compact.daily_research.attempts, undefined);
    assert.ok(JSON.stringify(compact).length < 1200);
});
