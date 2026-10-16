import test from "node:test";
import assert from "node:assert/strict";
import request from "supertest";
import { spawn } from "node:child_process";
import { chmod, mkdtemp, readdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { once } from "node:events";
import { setTimeout as delay } from "node:timers/promises";
import { TradingMcpClient, tradingInputs } from "../trading/client.js";
import { pythonCommand } from "../finance/client.js";
import { createApp } from "../app.js";
import { createAgent } from "../agent.js";
import { loopObservation } from "../agent-loop.js";

const id = "a".repeat(32);
const fixture = { id, status: "running", simulation_only: true, dashboard_url: `/?trading_job=${id}` };

test("trading routes validate requests and serve scoped artifacts", async () => {
    const calls = [];
    const app = createApp({ frontendPath: "/nonexistent", trading: {
        call: async (...args) => { calls.push(args); return args[0] === "trading_list" ? { jobs: [] } : fixture; },
        artifact: async (_id, name) => { assert.equal(_id, id); assert.equal(name, "report.html"); return Buffer.from("<h1>Simulation</h1>"); },
    } });
    await request(app).get("/trading/jobs").expect(200, { jobs: [] });
    await request(app).post("/trading/jobs").send({ mode: "watch", continuous: true, config: { symbols: ["SPY"] } }).expect(202);
    assert.equal(calls[1][0], "trading_start"); assert.equal(calls[1][1].continuous, true);
    await request(app).get(`/trading/jobs/${id}`).expect(200);
    await request(app).post(`/trading/jobs/${id}/stop`).send({}).expect(200);
    const artifact = await request(app).get(`/trading/jobs/${id}/artifacts/report.html`).expect(200);
    assert.match(artifact.headers["content-type"], /text\/html/);
    assert.match(artifact.headers["content-security-policy"], /sandbox/);
    assert.equal(artifact.text, "<h1>Simulation</h1>");
    const before = calls.length;
    await request(app).get("/trading/jobs/invalid").expect(400);
    await request(app).post("/trading/jobs").send({ mode: "live_orders" }).expect(400);
    await request(app).post("/trading/jobs").send({ mode: "demo", config: { risk: 0.5, costs: 0.1 } }).expect(400);
    await request(app).post("/trading/jobs").send({ mode: "demo", arbitrary: "ignored?" }).expect(400);
    assert.equal(calls.length, before);
});

test("agent loop starts one background job, retains its ID and exposes dashboard link", async () => {
    let calls = 0, steps = 0;
    const agent = createAgent({ tools: {}, trading: { call: async (name, args) => {
        calls++; assert.equal(name, "trading_start"); assert.equal(args.mode, "demo"); return fixture;
    } }, chains: { loop: { invoke: async (input) => {
        if (steps++ === 0) {
            assert.ok(input.allowed_tools.includes("trading_start"));
            return { action: "tool", tool: "trading_start", arguments: { mode: "demo" } };
        }
        assert.deepEqual(input.allowed_tools, []);
        assert.equal(JSON.parse(input.observations)[0].result.id, id);
        return { action: "finish", message: "Synthetic simulation started; inspect its progress in the trading dashboard." };
    } } } });
    const reply = await agent.run("Run a trading demo");
    assert.equal(calls, 1);
    assert.equal(reply.metadata.conversation_context.last_trading_job_id, id);
    assert.equal(reply.responses[0].trading_job.id, id);
    assert.equal(reply.usage.trading_start, 1);
    const compact = loopObservation({ ...fixture, progress: { equity: Array(10000).fill({ equity: 100 }), decisions: [], holdings: {} } }, "trading_status");
    assert.ok(JSON.stringify(compact).length < 1000);
    assert.throws(() => tradingInputs.trading_status.parse({ job_id: "../token" }));
});

test("research routes preserve dataset requests and validate bounded experiments", async () => {
    const calls = [];
    const datasetId = "b".repeat(64);
    const dataset = { source: "synthetic", symbols: ["DEMO_A"], start: "2026-10-01", end: "2026-10-14", interval: "30m", seed: 17 };
    const experiment = { dataset_id: datasetId, config: { symbols: ["DEMO_A"], interval: "30m" }, candidates: [{ kind: "trend_following", version: "1.0.0" }], train_sessions: 2, validation_sessions: 1, final_sessions: 2 };
    const app = createApp({ frontendPath: "/nonexistent", trading: { call: async (...args) => { calls.push(args); return fixture; } } });
    await request(app).get("/trading/strategies").expect(200);
    await request(app).post("/trading/strategies/validate").send({ kind: "mean_reversion", entry_z: 2 }).expect(200);
    await request(app).post("/trading/datasets").send(dataset).expect(202);
    assert.deepEqual(calls.at(-1), ["trading_dataset_create", { dataset }]);
    await request(app).get(`/trading/datasets/${datasetId}`).expect(200);
    await request(app).get("/trading/datasets?limit=5").expect(200);
    assert.deepEqual(calls.at(-1), ["trading_datasets", { limit: 5 }]);
    await request(app).post("/trading/experiments").send(experiment).expect(202);
    assert.equal(calls.at(-1)[1].experiment.finalize, false);
    assert.equal(calls.at(-1)[1].experiment.dataset_id, datasetId);
    await request(app).get("/trading/experiments").expect(200);
    await request(app).get(`/trading/experiments/${id}`).expect(200);
    await request(app).get(`/trading/experiments/${id}/attempts/${id}-0001`).expect(200);
    assert.deepEqual(calls.at(-1), ["trading_experiment_attempt", { experiment_id: id, attempt_id: `${id}-0001` }]);
    await request(app).post("/trading/experiments/compare").send({ experiment_ids: [id, "c".repeat(32)] }).expect(200);
    await request(app).post(`/trading/experiments/${id}/stop`).send({}).expect(200);
    assert.equal(calls.at(-1)[0], "trading_experiment_cancel");
    const before = calls.length;
    await request(app).get("/trading/datasets?limit=51").expect(400);
    await request(app).get("/trading/datasets/not-an-id").expect(400);
    await request(app).post("/trading/strategies/validate").send({ kind: "unsupported" }).expect(400);
    await request(app).post("/trading/experiments").send({ ...experiment, candidates: Array(13).fill({ kind: "trend_following" }) }).expect(400);
    await request(app).post("/trading/experiments/compare").send({ experiment_ids: [id, id] }).expect(400);
    await request(app).get(`/trading/experiments/${id}/attempts/${"c".repeat(32)}-0001`).expect(400);
    assert.equal(calls.length, before);
});

test("research agent submits once and keeps bounded provenance observations", async () => {
    const dataset = { source: "synthetic", symbols: ["TEST"], start: "2026-10-01", end: "2026-10-08", interval: "5m" };
    let calls = 0, steps = 0;
    const agent = createAgent({ tools: {}, trading: { call: async (name) => {
        calls++; assert.equal(name, "trading_dataset_create"); return fixture;
    } }, chains: { loop: { invoke: async (input) => {
        if (steps++ === 0) return { action: "tool", tool: "trading_dataset_create", arguments: { dataset } };
        assert.deepEqual(input.allowed_tools, []);
        return { action: "finish", message: "Dataset acquisition started; inspect the returned job ID." };
    } } } });
    const reply = await agent.run("Preserve this synthetic dataset");
    assert.equal(calls, 1);
    assert.equal(reply.metadata.conversation_context.last_trading_job_id, id);
    const compact = loopObservation({ ...fixture, experiment: { experiment_id: id, dataset_id: "b".repeat(64), assessment: "inconclusive", attempts: Array(160).fill({ data: "x".repeat(1000) }), split: { final_test_accessed: false } },
        progress: { decisions: [{ reason: "Cash", policy_audit: { response: "x".repeat(100000) } }] } }, "trading_experiment_status");
    assert.equal(compact.experiment.attempts, 160);
    assert.equal(compact.experiment.final_test_accessed, false);
    assert.ok(JSON.stringify(compact).length < 1500);
});

test("real trading MCP controls an independent runtime and produces offline reports", { timeout: 60000 }, async (t) => {
    const directory = await mkdtemp(join(tmpdir(), "trading-mcp-"));
    const previous = { data: process.env.TRADING_DATA_DIR, port: process.env.TRADING_RUNTIME_PORT };
    process.env.TRADING_DATA_DIR = directory;
    process.env.TRADING_RUNTIME_PORT = "0";
    const runtime = spawn(pythonCommand(), ["-m", "trading_agent.runtime", "--port", "0"], { stdio: ["ignore", "pipe", "pipe"] });
    let logs = "";
    runtime.stdout.on("data", (data) => { logs += data; });
    runtime.stderr.on("data", (data) => { logs += data; });
    const clients = [];
    t.after(async () => {
        for (const client of clients) await client.close();
        const ended = once(runtime, "exit");
        runtime.kill("SIGTERM");
        await ended;
        for (const [name, value] of [["TRADING_DATA_DIR", previous.data], ["TRADING_RUNTIME_PORT", previous.port]]) {
            if (value === undefined) delete process.env[name]; else process.env[name] = value;
        }
        async function unlock(path) {
            await chmod(path, 0o700);
            for (const entry of await readdir(path, { withFileTypes: true })) if (entry.isDirectory()) await unlock(join(path, entry.name));
        }
        await unlock(directory); // Immutable dataset directories need write permission only for fixture cleanup.
        await rm(directory, { recursive: true, force: true });
    });
    for (let attempt = 0; attempt < 150 && !/127\.0\.0\.1:(\d+)/.test(logs); attempt++) {
        if (runtime.exitCode !== null) assert.fail(logs);
        await delay(100);
    }
    const port = logs.match(/127\.0\.0\.1:(\d+)/)?.[1];
    assert.ok(port, logs);
    process.env.TRADING_RUNTIME_PORT = port;
    const client = new TradingMcpClient(); clients.push(client);
    await client.connect();
    assert.deepEqual(client.tools.map((tool) => tool.name).sort(), Object.keys(tradingInputs).sort());
    const discovery = await client.call("trading_strategies");
    assert.ok(discovery.strategies.some((strategy) => strategy.id === "opening_range_breakout"));
    assert.match(client.tools.find((tool) => tool.name === "trading_daily_research_start").description, /total-return proxies/);
    await assert.rejects(client.call("trading_daily_research_start", { research: { data_start: "2020-01-01", development_start: "2010-01-01" } }), /date|chronolog|ordered|before|start/i);
    const validated = await client.call("trading_validate_strategy", { strategy: { kind: "mean_reversion", entry_z: 2 } });
    assert.equal(validated.config.version, "1.0.0");
    await assert.rejects(client.call("trading_validate_strategy", { strategy: { kind: "mean_reversion", entry_z: 1, exit_z: 2 } }), /exit_z/);
    const started = await client.call("trading_start", { mode: "demo", start: "2026-10-14", config: { symbols: ["DEMO_A"], interval: "30m" } });
    assert.equal(started.status, "running");
    await client.close(); // Closing an MCP connection must not cancel its worker.
    const replacement = new TradingMcpClient(); clients.push(replacement);
    let job;
    for (let attempt = 0; attempt < 100; attempt++) {
        job = await replacement.call("trading_status", { job_id: started.id });
        if (job.status !== "running") break;
        await delay(100);
    }
    assert.equal(job.status, "complete", JSON.stringify(job));
    assert.match(job.report.source, /SYNTHETIC/);
    assert.equal(job.progress.completed_bars, 13);
    assert.ok(job.artifacts.includes("report.html"));
    assert.match((await replacement.artifact(job.id, "report.html")).toString(), /Simulation|simulated/);
    await assert.rejects(replacement.artifact(job.id, "../../token"), /Unknown report artifact/);
    await assert.rejects(replacement.call("trading_start", { mode: "watch", start: "2026-10-14" }), /watch uses upcoming/);
    await assert.rejects(replacement.call("trading_start", { mode: "backtest", start: "2026-01-01", end: "2026-10-01", config: { symbols: ["AAPL"], interval: "1m" } }), /recent 30 days/);
    const watch = await replacement.call("trading_start", { mode: "watch", continuous: true, config: { symbols: ["SPY"], poll_seconds: 3600 } });
    // Stop before any source data is needed; no external requests in this test.
    await replacement.call("trading_stop", { job_id: watch.id });
    for (let attempt = 0; attempt < 100; attempt++) {
        job = await replacement.call("trading_status", { job_id: watch.id });
        if (job.status !== "stopping") break;
        await delay(100);
    }
    assert.equal(job.status, "stopped");
    assert.equal((await replacement.call("trading_list")).jobs.length, 2);

    const datasetJob = await replacement.call("trading_dataset_create", { dataset: {
        source: "synthetic", symbols: ["DEMO_A"], start: "2026-10-01", end: "2026-10-14", interval: "30m", seed: 17,
    } });
    await replacement.close(); // Research workers also survive MCP reconnects.
    async function completed(name, jobId) {
        let result;
        for (let attempt = 0; attempt < 150; attempt++) {
            result = await replacement.call(name, { job_id: jobId });
            if (!["running", "stopping"].includes(result.status)) break;
            await delay(100);
        }
        assert.equal(result.status, "complete", JSON.stringify(result));
        return result;
    }
    const saved = await completed("trading_status", datasetJob.id);
    assert.match(saved.report.dataset_id, /^[a-f0-9]{64}$/);
    const manifest = await replacement.call("trading_dataset_inspect", { dataset_id: saved.report.dataset_id });
    assert.equal(manifest.dataset_id, saved.report.dataset_id);
    assert.equal((await replacement.call("trading_datasets", { limit: 5 })).datasets.length, 1);
    const specification = { dataset_id: saved.report.dataset_id, config: { symbols: ["DEMO_A"], interval: "30m" },
        candidates: [{ kind: "trend_following", fast_window: 1, slow_window: 2 }], train_sessions: 2, validation_sessions: 1, final_sessions: 2,
        cost_multipliers: [1, 2], finalize: false };
    const experiment = await replacement.call("trading_experiment_start", { experiment: specification });
    const research = await completed("trading_experiment_status", experiment.id);
    assert.equal(research.report.dataset_id, saved.report.dataset_id);
    assert.equal(research.report.experiment_id, experiment.id);
    assert.ok(research.experiment);
    const attemptId = research.experiment.attempts.find((attempt) => attempt.status === "complete").attempt_id;
    const attempt = await replacement.call("trading_experiment_attempt", { experiment_id: experiment.id, attempt_id: attemptId });
    assert.equal(attempt.experiment_id, experiment.id);
    assert.equal(attempt.attempt.reconciliation.ok, true);
    assert.ok(attempt.sessions.length <= 3);
    assert.ok(attempt.sessions.every((session) => session.equity.length <= 100 && session.fills.length <= 100 && session.decisions.length <= 50));
    assert.ok(research.artifacts.includes("experiment.json"));
    assert.equal((await replacement.call("trading_experiment_list", { limit: 5 })).jobs.length, 1);
    assert.match((await replacement.artifact(experiment.id, "experiment.json")).toString(), new RegExp(saved.report.dataset_id));
});
