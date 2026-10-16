import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
import { z } from "zod";
import { pythonCommand } from "../finance/client.js";

const root = fileURLToPath(new URL("../../", import.meta.url));
export const jobId = z.string().regex(/^[a-f0-9]{32}$/);
const datasetId = z.string().regex(/^[a-f0-9]{64}$/);
const listLimit = z.number().int().min(1).max(50).default(20);
export const tradingDescriptions = {
    trading_start: "Start one user-requested background simulation. mode demo uses synthetic data; backtest uses Yahoo completed dates; watch polls delayed Yahoo data. Yahoo backtests: 1m automatically fetched in 7-day batches within approximately the last 30 days; 2–30m within 60 days; 60m within 730 days. Ask before changing an explicit date range or interval. Only include config fields explicitly requested; omit all other settings to use validated defaults. continuous true watches all future sessions. Never starts real trades.",
    trading_status: "Inspect live simulation equity, positions, decisions and available reports for an exact job_id.",
    trading_list: "Find the latest persistent simulation jobs and their exact IDs.",
    trading_stop: "Gracefully stop a specific user-selected simulation; preserve partial positions and reports.",
    trading_strategies: "Discover versioned strategies, hypotheses, parameter requirements, warm-up rules and failure conditions.",
    trading_validate_strategy: "Validate a complete explicit strategy configuration without starting a simulation.",
    trading_dataset_create: "Create a user-requested immutable aggregated-bar dataset in a background job. Preserve exact symbols, dates and interval; Yahoo has restricted history. Poll trading_status for dataset_id and provenance.",
    trading_dataset_inspect: "Inspect one immutable dataset's quality report, original request, checksums and provenance.",
    trading_datasets: "List up to 50 immutable research datasets.",
    trading_experiment_start: "Start one user-requested bounded simulated experiment using a saved dataset, candidate configurations and explicit chronological train/validation/reserved-final periods. finalize true explicitly consumes the final test. Returns an experiment/job ID; inspect status instead of starting another job.",
    trading_experiment_status: "Read bounded experiment progress, candidate attempts, evidence assessment, provenance and artifacts for an exact experiment ID.",
    trading_daily_research_start: "Start one user-requested bounded daily ETF research study. Yahoo adjusted daily bars are total-return proxies, not trade/quote observations or executable fills. Compare preregistered trend hypotheses with matched benchmarks and cost stress; preserve reserved final dates. Returns a durable job/experiment ID immediately. Exploratory simulation only, not a validated strategy or profitable-edge claim. Never silently change requested symbols or dates.",
    trading_daily_research_status: "Inspect one daily research job's bounded progress, assessment, promotion status, provenance and daily-study artifact using its exact job ID. Use trading_stop to cancel. Completion does not validate a tradable edge.",
    trading_sector_research_start: "Start one user-requested frozen sector ETF momentum study: exactly four configurations, fixed universe and 2001–2022 training/validation dates. Yahoo daily adjusted bars are total-return proxies, not executable fills. Preserve reserved 2023–2025 prices without acquiring or evaluating them. Returns a durable job/experiment ID immediately. Exploratory simulation only, not a validated strategy or profitable-edge claim. Never alter the frozen hypothesis.",
    trading_sector_research_status: "Inspect one sector research job's bounded progress, assessment, promotion status, provenance and daily-study artifact using its exact job ID. Use trading_stop to cancel. Completion does not establish a tradable edge.",
    trading_weekly_research_start: "Start one user-requested frozen global ETF reversal study: exactly four configurations, fixed nine-fund universe and 2008–2022 development/validation dates. Completed weekly targets execute next session open; Yahoo adjusted bars remain total-return proxies, not executable fills. Preserve reserved 2023–2025 prices without acquiring or evaluating them. Returns a durable job/experiment ID immediately. Exploratory simulation only, not a validated strategy or profitable-edge claim. Never alter the frozen hypothesis.",
    trading_weekly_research_status: "Inspect one weekly reversal research job's bounded progress, assessment, promotion status, provenance and daily-study artifact using its exact job ID. Use trading_stop to cancel. Completion does not establish a tradable edge.",
    trading_experiment_attempt: "Review one saved attempt's bounded equity, fills, decisions and independent reconciliation using its exact experiment and attempt IDs.",
    trading_experiment_list: "List saved experiments and recent durable experiment job states.",
    trading_experiment_compare: "Compare two to six experiments with matching immutable data, capital, costs, risk and validation periods. Incompatible comparisons fail explicitly.",
    trading_experiment_cancel: "Gracefully cancel a selected experiment, preserving attempted configurations and partial evidence.",
};
const strategyInput = z.object({ kind: z.enum(["sma", "momentum", "buy_and_hold", "ollama", "trend_following", "mean_reversion", "opening_range_breakout"]).optional(),
    version: z.literal("1.0.0").optional(),
    fast_window: z.number().int().min(1).max(100).optional(), slow_window: z.number().int().min(2).max(500).optional(),
    momentum_threshold: z.number().min(0).max(1).optional(), target_gross_weight: z.number().min(0).max(1).optional(),
    model: z.string().min(1).max(120).optional(), ollama_host: z.url().optional(), model_timeout_seconds: z.number().min(1).max(120).optional(),
    entry_z: z.number().positive().max(10).optional(), exit_z: z.number().min(0).max(10).optional(), opening_range_bars: z.number().int().min(1).max(100).optional(),
}).strict();
const configInput = z.object({ symbols: z.array(z.string().trim().min(1).max(20)).min(1).max(10).optional(),
    interval: z.enum(["1m", "2m", "5m", "15m", "30m", "60m"]).optional(), initial_cash: z.number().positive().max(1e12).optional(), currency: z.literal("USD").optional(),
    strategy: strategyInput.optional(), risk: z.object({ max_position_weight: z.number().positive().max(1).optional(),
        daily_loss_limit: z.number().positive().max(1).optional(), max_consecutive_decision_errors: z.number().int().min(1).max(20).optional() }).strict().optional(),
    costs: z.object({ commission_bps: z.number().min(0).max(1000).optional(), slippage_bps: z.number().min(0).max(1000).optional(), fixed_fee: z.number().min(0).max(1000).optional() }).strict().optional(),
    poll_seconds: z.number().min(1).max(3600).optional(), data_lag_seconds: z.number().min(0).max(3600).optional(),
    close_grace_seconds: z.number().min(0).max(3600).optional(), max_data_errors: z.number().int().min(1).max(20).optional(),
}).strict().describe("Only explicitly requested settings. Omit other keys for defaults. risk and costs are objects, never numbers.");
const datasetInput = z.object({ source: z.enum(["synthetic", "yahoo"]),
    symbols: z.array(z.string().trim().min(1).max(20)).min(1).max(10),
    start: z.string().regex(/^\d{4}-\d{2}-\d{2}$/), end: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
    interval: z.enum(["1m", "2m", "5m", "15m", "30m", "60m"]), seed: z.number().int().min(0).max(2**32 - 1).optional(),
}).strict();
const experimentInput = z.object({ dataset_id: datasetId, config: configInput,
    candidates: z.array(strategyInput).min(1).max(12), train_sessions: z.number().int().min(2).max(200),
    validation_sessions: z.number().int().min(1).max(60), final_sessions: z.number().int().min(2).max(60),
    cost_multipliers: z.array(z.number().min(1).max(5)).min(2).max(3).optional(), finalize: z.boolean().default(false),
    parent_experiment_id: jobId.nullable().optional(),
}).strict();
const dailyResearchInput = z.object({ source: z.literal("yahoo").optional(),
    symbols: z.array(z.enum(["SPY", "IEF", "GLD"])).length(3).refine((values) => values.join(",") === "SPY,IEF,GLD", "The pilot freezes the universe and order to SPY, IEF, GLD").optional(),
    data_start: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).optional(), development_start: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).optional(),
    validation_start: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).optional(), development_end: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).optional(),
    reserved_final_start: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).optional(), reserved_final_end: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).optional(),
    initial_cash: z.number().positive().max(1e12).optional(),
    cost_bps: z.array(z.number().min(0).max(100)).min(1).max(3).refine((values) => values.every((value, index) => index === 0 || values[index - 1] < value), "Use sorted distinct costs").optional(),
    lookbacks: z.array(z.number().int().min(63).max(252)).min(1).max(3).refine((values) => values.every((value, index) => index === 0 || values[index - 1] < value), "Use sorted distinct lookbacks").optional(),
}).strict().describe("Bounded daily total-return proxy research. Omit settings for the declared pilot defaults. Runtime validates chronological periods and distinct parameter/cost scenarios.");
const sectorResearchInput = z.object({ source: z.literal("yahoo").optional(),
    symbols: z.array(z.enum(["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY", "SPY"])).length(10).refine((values) => values.join(",") === "XLB,XLE,XLF,XLI,XLK,XLP,XLU,XLV,XLY,SPY", "The protocol freezes the universe and order").optional(),
    data_start: z.literal("2000-01-03").optional(), development_start: z.literal("2001-01-02").optional(),
    validation_start: z.literal("2013-01-02").optional(), development_end: z.literal("2022-12-30").optional(),
    reserved_final_start: z.literal("2023-01-03").optional(), reserved_final_end: z.literal("2025-12-31").optional(),
    initial_cash: z.literal(100000).optional(),
    cost_bps: z.tuple([z.literal(5), z.literal(10), z.literal(20)]).optional(),
}).strict().describe("Frozen four-configuration sector momentum protocol. Omit settings for its declared defaults. Symbols, dates, capital and parameter grid cannot be changed.");
const weeklyResearchInput = z.object({ source: z.literal("yahoo").optional(),
    symbols: z.array(z.enum(["SPY", "IWM", "QQQ", "EFA", "EEM", "IEF", "TLT", "GLD", "DBC"])).length(9).refine((values) => values.join(",") === "SPY,IWM,QQQ,EFA,EEM,IEF,TLT,GLD,DBC", "The protocol freezes the universe and order").optional(),
    data_start: z.literal("2007-01-03").optional(), development_start: z.literal("2008-01-02").optional(),
    validation_start: z.literal("2013-01-02").optional(), development_end: z.literal("2022-12-30").optional(),
    reserved_final_start: z.literal("2023-01-03").optional(), reserved_final_end: z.literal("2025-12-31").optional(),
    initial_cash: z.literal(100000).optional(),
    cost_bps: z.tuple([z.literal(5), z.literal(10), z.literal(20)]).optional(),
}).strict().describe("Frozen four-configuration global weekly reversal protocol. Omit settings for declared defaults. Symbols, dates, capital and parameter grid cannot be changed.");
export const tradingInputs = {
    trading_start: z.object({ mode: z.enum(["demo", "backtest", "watch"]).default("demo"), config: configInput.optional(),
        start: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).optional(), end: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).optional(),
        sessions: z.number().int().min(1).max(252).default(1), continuous: z.boolean().default(false) }).strict(),
    trading_status: z.object({ job_id: jobId }).strict(),
    trading_list: z.object({}).strict(),
    trading_stop: z.object({ job_id: jobId }).strict(),
    trading_strategies: z.object({}).strict(),
    trading_validate_strategy: z.object({ strategy: strategyInput }).strict(),
    trading_dataset_create: z.object({ dataset: datasetInput }).strict(),
    trading_dataset_inspect: z.object({ dataset_id: datasetId }).strict(),
    trading_datasets: z.object({ limit: listLimit }).strict(),
    trading_experiment_start: z.object({ experiment: experimentInput }).strict(),
    trading_experiment_status: z.object({ job_id: jobId }).strict(),
    trading_daily_research_start: z.object({ research: dailyResearchInput }).strict(),
    trading_daily_research_status: z.object({ job_id: jobId }).strict(),
    trading_sector_research_start: z.object({ research: sectorResearchInput }).strict(),
    trading_sector_research_status: z.object({ job_id: jobId }).strict(),
    trading_weekly_research_start: z.object({ research: weeklyResearchInput }).strict(),
    trading_weekly_research_status: z.object({ job_id: jobId }).strict(),
    trading_experiment_attempt: z.object({ experiment_id: jobId, attempt_id: z.string().regex(/^[a-f0-9]{32}-\d{4}$/) }).strict().refine((value) => value.attempt_id.startsWith(`${value.experiment_id}-`), "Use an attempt belonging to this experiment"),
    trading_experiment_list: z.object({ limit: listLimit }).strict(),
    trading_experiment_compare: z.object({ experiment_ids: z.array(jobId).min(2).max(6).refine((ids) => new Set(ids).size === ids.length, "Use distinct experiment IDs") }).strict(),
    trading_experiment_cancel: z.object({ job_id: jobId }).strict(),
};
const job = z.object({ id: jobId, status: z.enum(["running", "stopping", "complete", "stopped", "failed", "interrupted"]), simulation_only: z.literal(true) }).passthrough();

export class TradingMcpClient {
    constructor({ command = pythonCommand(), args = ["-m", "trading_agent.mcp_server"] } = {}) {
        this.command = command;
        this.args = args;
        this.connection = null;
        this.client = null;
    }

    async connect() {
        if (!this.connection) this.connection = (async () => {
            const client = new Client({ name: "assistant-trading-client", version: "1.0.0" });
            this.client = client;
            client.onclose = () => { if (this.client === client) { this.connection = null; this.client = null; } };
            try {
                await client.connect(new StdioClientTransport({ command: this.command, args: this.args, cwd: root, stderr: "inherit", env: {
                    ...Object.fromEntries(Object.entries(process.env).filter(([name, value]) => ["TRADING_DATA_DIR", "TRADING_RUNTIME_PORT"].includes(name) && value !== undefined)),
                } }), { timeout: 15000 });
                const { tools } = await client.listTools({}, { timeout: 10000 });
                for (const name of Object.keys(tradingInputs)) if (!tools.some((tool) => tool.name === name)) throw new Error(`Missing trading tool: ${name}`);
                this.tools = tools;
                return client;
            } catch (error) {
                await client.close();
                throw new Error(`Trading MCP could not start. Install the Python framework and backend/finance/requirements.txt. ${error.message}`);
            }
        })();
        return this.connection;
    }

    async call(name, args = {}) {
        if (!Object.hasOwn(tradingInputs, name)) throw new Error("Unknown trading tool");
        const input = tradingInputs[name].parse(args);
        const client = await this.connect();
        const result = await client.callTool({ name, arguments: input }, undefined, { timeout: 15000 });
        const text = result.content?.filter((item) => item.type === "text").map((item) => item.text).join("\n");
        if (result.isError) throw new Error(text || "Trading tool failed");
        const data = result.structuredContent || JSON.parse(text);
        if (name === "trading_list") return z.object({ jobs: z.array(z.object({ id: jobId, status: z.string() }).passthrough()) }).parse(data);
        if (["trading_start", "trading_status", "trading_stop", "trading_dataset_create", "trading_experiment_start", "trading_experiment_status", "trading_daily_research_start", "trading_daily_research_status", "trading_sector_research_start", "trading_sector_research_status", "trading_weekly_research_start", "trading_weekly_research_status", "trading_experiment_cancel"].includes(name)) return job.parse(data);
        if (name === "trading_strategies") return z.object({ strategies: z.array(z.object({}).passthrough()).max(20) }).parse(data);
        if (name === "trading_datasets") return z.object({ datasets: z.array(z.object({}).passthrough()).max(50) }).parse(data);
        if (name === "trading_experiment_list") return z.object({ experiments: z.array(z.object({}).passthrough()).max(50), jobs: z.array(z.object({}).passthrough()).max(50) }).parse(data);
        return z.object({}).passthrough().parse(data);
    }

    async artifact(id, name) {
        jobId.parse(id);
        if (!["report.html", "report.md", "report.json", "summary.json", "experiment.json", "attempts.jsonl", "daily-study.json", "data-manifest.json", "performance.png", "executions.png", "daily_pnl.png", "equity.csv", "fills.csv", "decisions.json"].includes(name)) throw Object.assign(new Error("Unknown report artifact"), { status: 404 });
        const token = (await readFile(resolve(process.env.TRADING_DATA_DIR || `${root}artifacts/trading/runtime`, "token"), "utf8")).trim();
        const response = await fetch(`http://127.0.0.1:${Number(process.env.TRADING_RUNTIME_PORT || 2612)}/jobs/${id}/artifacts/${name}`, {
            headers: { Authorization: `Bearer ${token}` }, signal: AbortSignal.timeout(10000),
        });
        if (!response.ok) throw Object.assign(new Error("Report artifact is not available"), { status: response.status });
        return Buffer.from(await response.arrayBuffer());
    }

    async close() {
        await this.client?.close();
        this.connection = null;
        this.client = null;
    }
}
