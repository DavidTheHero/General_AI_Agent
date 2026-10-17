import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { ErrorCode } from "@modelcontextprotocol/sdk/types.js";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { join } from "node:path";
import { z } from "zod";

const root = fileURLToPath(new URL("../../", import.meta.url));
export const pythonCommand = ({ platform = process.platform, rootDirectory = root, env = process.env, exists = existsSync } = {}) => {
    const envPython = env.MCP_PYTHON;
    if (typeof envPython === "string" && envPython.length > 0) return envPython;
    const localPython = join(rootDirectory, ".venv", platform === "win32" ? "Scripts/python.exe" : "bin/python");
    if (exists(localPython)) return localPython;
    return platform === "win32" ? "python" : "python3";
};
const barSchema = z.object({ symbol: z.string(), date: z.string(), timestamp: z.string(),
    open: z.number(), high: z.number(), low: z.number(), close: z.number(), volume: z.number() });
const metadataSchema = z.object({ symbol: z.string(), currency: z.string(), exchange: z.string(),
    timezone: z.string(), source: z.string(), adjusted: z.boolean() });
const schemas = {
    exchange_rate: z.object({ from_currency: z.string(), to_currency: z.string(), rate: z.number().positive(), date: z.string(), timestamp: z.string(), source: z.string() }),
    search_stocks: z.object({ source: z.string(), quotes: z.array(z.object({ symbol: z.string(), name: z.string(), exchange: z.string() })) }),
    stock_history: metadataSchema.extend({ history: z.array(barSchema).min(1) }),
    stock_quote: metadataSchema.extend({ price: z.number(), date: z.string(), timestamp: z.string(), change: z.number().nullable(), percent_change: z.number().nullable() }),
};
export const packageTools = ["ticker_data", "price_history", "download_prices", "search_finance", "lookup_instruments", "market_data", "calendar_events", "fund_data", "sector_data", "industry_data", "option_chain", "screener_catalog", "screen_instruments", "stream_prices"];
const packageResult = z.object({ source: z.string(), retrieved_at: z.string(), data: z.unknown(), truncated: z.boolean() });
for (const name of packageTools) schemas[name] = packageResult;

export class FinanceMcpClient {
    constructor({ command = pythonCommand(), args = [fileURLToPath(new URL("./server.py", import.meta.url))], timeout = 30000 } = {}) {
        this.command = command;
        this.args = args;
        this.timeout = timeout;
        this.connection = null;
        this.client = null;
        this.queue = Promise.resolve();
    }

    async connect() {
        if (!this.connection) {
            this.connection = (async () => {
                const client = new Client({ name: "assistant-finance-client", version: "1.0.0" });
                this.client = client;
                client.onclose = () => { if (this.client === client) { this.connection = null; this.client = null; } };
                try {
                    await client.connect(new StdioClientTransport({ command: this.command, args: this.args, cwd: root, stderr: "inherit" }), { timeout: this.timeout });
                    const { tools } = await client.listTools({}, { timeout: this.timeout });
                    for (const name of Object.keys(schemas)) {
                        if (!tools.some((tool) => tool.name === name)) throw new Error(`Missing MCP finance tool: ${name}`);
                    }
                    this.tools = tools;
                    return client;
                } catch (error) {
                    await client.close();
                    throw new Error(`Finance MCP server could not start. Install backend/finance/requirements.txt and check MCP_PYTHON. ${error.message}`);
                }
            })();
        }
        return this.connection;
    }

    async call(name, args) {
        if (!schemas[name]) throw new Error(`Unsupported finance tool: ${name}`);
        const work = this.queue.then(async () => {
            const client = await this.connect();
            let result;
            try {
                result = await client.callTool({ name, arguments: args }, undefined, { timeout: this.timeout });
            } catch (error) {
                if (error.code === ErrorCode.RequestTimeout) {
                    await client.close();
                    throw new Error(`Finance MCP (${name}) timed out. Please try again.`);
                }
                throw error;
            }
            const text = result.content?.filter((item) => item.type === "text").map((item) => item.text).join("\n");
            if (result.isError) throw new Error(`Finance MCP (${name}): ${text || "tool failed"}`);
            return schemas[name].parse(result.structuredContent || JSON.parse(text));
        });
        this.queue = work.catch(() => {});
        return work;
    }

    async close() {
        await this.queue;
        await this.client?.close();
        this.connection = null;
        this.client = null;
    }
}
