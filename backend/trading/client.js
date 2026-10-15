import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
import { z } from "zod";
import { pythonCommand } from "../finance/client.js";

const root = fileURLToPath(new URL("../../", import.meta.url));
export const jobId = z.string().regex(/^[a-f0-9]{32}$/);
export const tradingDescriptions = {
    trading_start: "Start one user-requested background simulation. mode demo uses synthetic data; backtest uses Yahoo completed dates; watch polls delayed Yahoo data. Yahoo backtests: 1m automatically fetched in 7-day batches within approximately the last 30 days; 2–30m within 60 days; 60m within 730 days. Ask before changing an explicit date range or interval. Only include config fields explicitly requested; omit all other settings to use validated defaults. continuous true watches all future sessions. Never starts real trades.",
    trading_status: "Inspect live simulation equity, positions, decisions and available reports for an exact job_id.",
    trading_list: "Find the latest persistent simulation jobs and their exact IDs.",
    trading_stop: "Gracefully stop a specific user-selected simulation; preserve partial positions and reports.",
};
const strategyInput = z.object({ kind: z.enum(["sma", "momentum", "buy_and_hold", "ollama"]).optional(),
    fast_window: z.number().int().min(1).max(100).optional(), slow_window: z.number().int().min(2).max(500).optional(),
    momentum_threshold: z.number().min(0).max(1).optional(), target_gross_weight: z.number().min(0).max(1).optional(),
    model: z.string().min(1).max(120).optional(), ollama_host: z.url().optional(), model_timeout_seconds: z.number().min(1).max(120).optional(),
}).strict();
const configInput = z.object({ symbols: z.array(z.string().trim().min(1).max(20)).min(1).max(10).optional(),
    interval: z.enum(["1m", "2m", "5m", "15m", "30m", "60m"]).optional(), initial_cash: z.number().positive().max(1e12).optional(), currency: z.literal("USD").optional(),
    strategy: strategyInput.optional(), risk: z.object({ max_position_weight: z.number().positive().max(1).optional(),
        daily_loss_limit: z.number().positive().max(1).optional(), max_consecutive_decision_errors: z.number().int().min(1).max(20).optional() }).strict().optional(),
    costs: z.object({ commission_bps: z.number().min(0).max(1000).optional(), slippage_bps: z.number().min(0).max(1000).optional(), fixed_fee: z.number().min(0).max(1000).optional() }).strict().optional(),
    poll_seconds: z.number().min(1).max(3600).optional(), data_lag_seconds: z.number().min(0).max(3600).optional(),
    close_grace_seconds: z.number().min(0).max(3600).optional(), max_data_errors: z.number().int().min(1).max(20).optional(),
}).strict().describe("Only explicitly requested settings. Omit other keys for defaults. risk and costs are objects, never numbers.");
export const tradingInputs = {
    trading_start: z.object({ mode: z.enum(["demo", "backtest", "watch"]).default("demo"), config: configInput.optional(),
        start: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).optional(), end: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).optional(),
        sessions: z.number().int().min(1).max(252).default(1), continuous: z.boolean().default(false) }).strict(),
    trading_status: z.object({ job_id: jobId }).strict(),
    trading_list: z.object({}).strict(),
    trading_stop: z.object({ job_id: jobId }).strict(),
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
        return name === "trading_list" ? z.object({ jobs: z.array(z.object({ id: jobId, status: z.string() }).passthrough()) }).parse(data) : job.parse(data);
    }

    async artifact(id, name) {
        jobId.parse(id);
        if (!["report.html", "report.md", "report.json", "performance.png", "executions.png", "daily_pnl.png", "equity.csv", "fills.csv", "decisions.json"].includes(name)) throw Object.assign(new Error("Unknown report artifact"), { status: 404 });
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
