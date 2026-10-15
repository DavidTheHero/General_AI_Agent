import express from "express";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { z } from "zod";
import { defaultMemory } from "./memory.js";
import { workspaceRequest } from "./finance/workspace.js";
import { jobId, tradingInputs } from "./trading/client.js";

const sessionId = z.string().trim().min(1);
const contextSchema = z.object({
    session_id: sessionId.optional(),
    conversation_id: sessionId.optional(),
    session: sessionId.optional(),
    response_mode: z.enum(["api", "natural"]).optional(),
    stock_context: z.object({
        last_quote: z.object({ symbol: z.string(), price: z.number().finite().nonnegative(), currency: z.string(), date: z.string() }).passthrough().nullable().optional(),
        recent_symbols: z.array(z.string()).optional(),
        comparison_history: z.array(z.record(z.string(), z.unknown())).optional(),
        last_comparison: z.object({
            entries: z.array(z.object({ symbol: z.string(), start: z.number(), end: z.number(), change_pct: z.number() })),
            days: z.number(),
        }).passthrough().nullable().optional(),
    }).passthrough().optional(),
    weather_context: z.record(z.string(), z.unknown()).optional(),
    fact_context: z.object({ recent_facts: z.array(z.record(z.string(), z.unknown())).optional() }).passthrough().optional(),
    time_context: z.record(z.string(), z.unknown()).optional(),
    user_profile: z.object({ reminders: z.array(z.record(z.string(), z.unknown())).optional() }).passthrough().optional(),
}).passthrough();

export function createApp({ agent, store, workspace, trading, frontendPath = fileURLToPath(new URL("../frontend/dist", import.meta.url)) }) {
    const app = express();
    app.use(express.json({ limit: "1mb" }));
    app.get("/health", (_request, response) => response.json({ status: "ok" }));
    if (trading) {
        app.get("/trading/jobs", async (_request, response) => response.set("Cache-Control", "no-store").json(await trading.call("trading_list")));
        app.post("/trading/jobs", async (request, response) => response.status(202).json(await trading.call("trading_start", tradingInputs.trading_start.parse(request.body))));
        app.get("/trading/jobs/:id", async (request, response) => response.set("Cache-Control", "no-store").json(await trading.call("trading_status", { job_id: jobId.parse(request.params.id) })));
        app.post("/trading/jobs/:id/stop", async (request, response) => response.json(await trading.call("trading_stop", { job_id: jobId.parse(request.params.id) })));
        app.get("/trading/jobs/:id/artifacts/:name", async (request, response) => {
            const content = await trading.artifact(jobId.parse(request.params.id), request.params.name);
            response.set("Cache-Control", "no-store").set("X-Content-Type-Options", "nosniff");
            response.set("Content-Security-Policy", "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; sandbox");
            response.type(request.params.name).send(content);
        });
    }
    if (workspace) app.post("/finance/workspace", async (request, response) => {
        response.json(await workspace.run(workspaceRequest.parse(request.body)));
    });
    app.post("/query", async (request, response) => {
        const { query, metadata } = z.object({ query: z.string().trim().min(1), metadata: contextSchema.nullable().optional() }).parse(request.body);
        response.json(await agent.run(query, metadata || {}));
    });
    app.post("/memory/reset", (request, response) => {
        const { session_id = null } = z.object({ session_id: sessionId.nullable().optional() }).parse(request.body);
        if (session_id) store.deleteSession(session_id);
        response.json({ metadata: defaultMemory(), session_id });
    });
    app.post("/memory/search", (request, response) => {
        const { session_id, query, top_k } = z.object({ session_id: sessionId, query: z.string(), top_k: z.number().int().min(1).max(200).nullable().optional() }).parse(request.body);
        response.json({ matches: store.query(session_id, query, top_k || 5), session_id });
    });
    if (existsSync(frontendPath)) {
        app.use(express.static(frontendPath));
        app.get("/", (_request, response) => response.sendFile(`${frontendPath}/index.html`));
    }
    app.use((error, _request, response, _next) => {
        const status = error instanceof z.ZodError ? 400 : (error.status || 500);
        const detail = error instanceof z.ZodError ? error.issues.map((issue) => `${issue.path.join(".")}: ${issue.message}`).join("; ") : error.message;
        response.status(status).json({ detail, error: detail });
    });
    return app;
}
