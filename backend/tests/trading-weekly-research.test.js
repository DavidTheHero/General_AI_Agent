import test from "node:test";
import assert from "node:assert/strict";
import request from "supertest";
import { createApp } from "../app.js";
import { TradingMcpClient, tradingDescriptions, tradingInputs } from "../trading/client.js";
import { loopObservation } from "../agent-loop.js";

const id = "a".repeat(32);
const universe = ["SPY", "IWM", "QQQ", "EFA", "EEM", "IEF", "TLT", "GLD", "DBC"];

test("weekly research routes preserve frozen inputs and scope job lists", async () => {
    const calls = [];
    const fixture = { id, status: "running", simulation_only: true, request: { mode: "weekly_research" } };
    const app = createApp({ frontendPath: "/nonexistent", trading: { call: async (...args) => {
        calls.push(args);
        return args[0] === "trading_list" ? { jobs: [fixture,
            { id: "b".repeat(32), request: { mode: "daily_research" } },
            { id: "c".repeat(32), request: { mode: "sector_research" } }] } : fixture;
    } } });
    const research = { symbols: universe, data_start: "2007-01-03", development_start: "2008-01-02",
        development_end: "2022-12-30", cost_bps: [5, 10, 20] };
    await request(app).post("/trading/weekly-research").send(research).expect(202, fixture);
    assert.deepEqual(calls.at(-1), ["trading_weekly_research_start", { research }]);
    await request(app).get(`/trading/weekly-research/${id}`).expect(200, fixture);
    assert.deepEqual(calls.at(-1), ["trading_weekly_research_status", { job_id: id }]);
    for (const [mode, expected] of [["weekly", id], ["daily", "b".repeat(32)], ["sector", "c".repeat(32)]]) {
        const listed = await request(app).get(`/trading/${mode}-research`).expect(200);
        assert.deepEqual(listed.body.jobs.map((job) => job.id), [expected]);
        assert.equal(listed.headers["cache-control"], "no-store");
    }
    const before = calls.length;
    await request(app).get("/trading/weekly-research/invalid").expect(400);
    for (const invalid of [{ cost_bps: [5] }, { development_end: "2023-12-29" }, { finalize: true }, { holdings: 2 }]) {
        await request(app).post("/trading/weekly-research").send(invalid).expect(400);
    }
    assert.equal(calls.length, before);
});

test("weekly schemas forbid scope, cost and holdout overrides", () => {
    assert.match(tradingDescriptions.trading_weekly_research_start, /exactly four configurations/);
    assert.match(tradingDescriptions.trading_weekly_research_start, /without acquiring or evaluating/);
    assert.match(tradingDescriptions.trading_weekly_research_start, /not a validated strategy/);
    assert.deepEqual(tradingInputs.trading_weekly_research_start.parse({ research: {} }), { research: {} });
    const frozen = { source: "yahoo", symbols: universe, data_start: "2007-01-03", development_start: "2008-01-02",
        validation_start: "2013-01-02", development_end: "2022-12-30", reserved_final_start: "2023-01-03",
        reserved_final_end: "2025-12-31", initial_cash: 100000, cost_bps: [5, 10, 20] };
    assert.deepEqual(tradingInputs.trading_weekly_research_start.parse({ research: frozen }).research, frozen);
    for (const research of [{ source: "synthetic" }, { lookback: 5 }, { holdings: 3 }, { interval: "1d" },
        { symbols: universe.toReversed() }, { symbols: [...universe.slice(0, -1), "VNQ"] },
        { data_start: "2005-01-03" }, { development_start: "2006-01-03" }, { validation_start: "2014-01-02" },
        { development_end: "2023-12-29" }, { reserved_final_start: "2024-01-02" }, { reserved_final_end: "2026-01-02" },
        { initial_cash: 99999 }, { cost_bps: [5, 10, 30] }, { cost_bps: [0, 5, 10] }, { finalize: true }]) {
        assert.throws(() => tradingInputs.trading_weekly_research_start.parse({ research }));
    }
});

test("weekly status keeps evidence references bounded", () => {
    const compact = loopObservation({ id, status: "complete", daily_research: {
        assessment: "inconclusive", promotion_status: "research_only", reserved_final: { accessed: false },
        provenance_ref: "daily-studies/fixture/dataset/manifest.json", attempts: Array(100).fill({ rows: "x".repeat(10000) }),
        comparisons: Array(100).fill({ rows: "x".repeat(10000) }),
    } }, "trading_weekly_research_status");
    assert.equal(compact.daily_research.reserved_final.accessed, false);
    assert.equal(compact.daily_research.attempts, undefined);
    assert.equal(compact.daily_research.comparisons, undefined);
    assert.ok(JSON.stringify(compact).length < 1200);
});

test("real stdio MCP discovery exposes the bounded weekly contract", async () => {
    const client = new TradingMcpClient();
    try {
        await client.connect();
        const tool = client.tools.find((item) => item.name === "trading_weekly_research_start");
        assert.match(tool.description, /four configurations/);
        assert.match(tool.description, /total-return proxies/);
        assert.ok(client.tools.some((item) => item.name === "trading_weekly_research_status"));
        await assert.rejects(client.call("trading_weekly_research_start", { research: { finalize: true } }));
    } finally {
        await client.close();
    }
});
