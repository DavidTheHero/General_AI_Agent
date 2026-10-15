import { z } from "zod";

export const loopStepSchema = z.object({
    action: z.enum(["tool", "finish", "clarify"]),
    tool: z.string().default(""),
    arguments: z.record(z.string(), z.unknown()).default({}),
    message: z.string().max(2000).default(""),
});

function fingerprint(tool, args) {
    const ordered = (value) => Array.isArray(value) ? value.map(ordered) : value && typeof value === "object"
        ? Object.fromEntries(Object.keys(value).sort().map((key) => [key, ordered(value[key])])) : value;
    return JSON.stringify([tool, ordered(args)]);
}

export function loopObservation(result, tool = "", args = {}) {
    if (tool.startsWith("trading_") && result?.id) return {
        id: result.id, status: result.status, simulation_only: true, dashboard_url: result.dashboard_url,
        error: result.error, report: result.report,
        progress: result.progress ? { state: result.progress.state, source: result.progress.source, session: result.progress.session,
            valuation_timestamp: result.progress.valuation_timestamp, completed_bars: result.progress.completed_bars,
            latest_equity: result.progress.equity?.at(-1), holdings: result.progress.holdings, latest_decision: result.progress.decisions?.at(-1) } : null,
    };
    if (tool === "resolve_company") return { status: result.status, request: result.request, company: result.company,
        candidates: result.candidates, unverified_candidates: result.unverified_candidates?.slice(0, 3), errors: result.errors, limitation: result.limitation };
    if (tool === "mcp.ticker_data" && args.dataset === "info" && result?.data && typeof result.data === "object") {
        const fields = ["symbol", "longName", "shortName", "country", "exchange", "fullExchangeName", "quoteType", "currency", "website", "sector", "industry"];
        return { source: result.source, retrieved_at: result.retrieved_at,
            data: Object.fromEntries(fields.filter((field) => result.data[field] !== undefined).map((field) => [field, result.data[field]])),
            selected_fields: true };
    }
    const evidence = result?.report ? { answer: result.answer, report: {
        workflow: result.report.workflow, source: result.report.source, generated_at: result.report.generated_at,
        data: result.report.data, warnings: result.report.warnings,
    } } : result;
    const text = JSON.stringify(evidence) ?? "null";
    return text.length <= 2500 ? evidence : { truncated: true, preview: text.slice(0, 2500), note: "Only this preview is available as evidence; request a narrower dataset for missing details." };
}

// Decisions are model-driven; execution, observations and stop conditions belong to the host.
export async function runAgentLoop({ choose, execute, availableTools, seed, maxSteps = 6, requireReport = false, finishOnReport = false }) {
    const observations = [], trace = [], seen = new Set(), rejectedRepeats = new Set();
    let report = null;
    const stop = (reason, answer) => ({ answer, report, observations, trace, stop_reason: reason });
    for (let step = 0; step <= maxSteps; step++) {
        let decision;
        try { decision = loopStepSchema.parse(step === 0 && seed ? seed : await choose(observations, maxSteps - step)); }
        catch (error) {
            trace.push({ step: step + 1, action: "planner_error", message: error.message });
            return stop("planner_error", "I couldn’t decide the next step reliably. Please try again or make the request more specific.");
        }
        if (decision.action !== "tool") {
            if (!decision.message.trim()) return stop("invalid_answer", "Please clarify what you would like me to investigate.");
            trace.push({ step: step + 1, action: decision.action });
            if (decision.action === "finish" && observations.length && !observations.some((item) => item.status === "ok")) {
                return stop("no_evidence", "I couldn’t retrieve usable evidence for this request. You can try again or provide the exact company name and exchange.");
            }
            if (decision.action === "finish" && requireReport && !report) return stop("incomplete", "I couldn’t complete a verified company report. You can try again, or provide the exact listed company name, country, and Yahoo ticker. No report data has been estimated.");
            return stop(decision.action === "finish" ? "complete" : "clarification", decision.message);
        }
        if (step === maxSteps) return stop("step_limit", "I reached the investigation limit. The available results are incomplete; please narrow the request or provide a company ticker and exchange.");
        const key = fingerprint(decision.tool, decision.arguments);
        if (seen.has(key)) {
            if (rejectedRepeats.has(key)) return stop("repeated_action", "That lookup would repeat an earlier action without new information. Please provide a more specific company name, ticker, or exchange so I can continue.");
            rejectedRepeats.add(key);
            observations.push({ tool: decision.tool, arguments: decision.arguments, status: "error", error: "Repeated call blocked. This action already ran; use its previous observation. Choose a different action to advance the goal or finish with existing evidence." });
            trace.push({ step: step + 1, action: "tool", tool: decision.tool, status: "blocked_repeat" });
            continue;
        }
        seen.add(key);
        const entry = { step: step + 1, action: "tool", tool: decision.tool, arguments: decision.arguments };
        try {
            if (!availableTools.has(decision.tool)) throw new Error(`Unknown tool: ${decision.tool}. Choose a listed tool.`);
            const result = await execute(decision.tool, decision.arguments);
            if (result?.report) report = result.report;
            observations.push({ tool: decision.tool, arguments: decision.arguments, status: "ok", result: loopObservation(result, decision.tool, decision.arguments) });
            trace.push({ ...entry, status: "ok", ...(Array.isArray(result?.attempts) ? { attempts: result.attempts, resolution_status: result.status } : {}) });
            if (report && finishOnReport) {
                trace.push({ step: step + 2, action: "finish", completion: "report_ready" });
                return stop("complete", result.answer || "Your report is ready. Inspect its sources and data-availability notices below.");
            }
        } catch (error) {
            observations.push({ tool: decision.tool, arguments: decision.arguments, status: "error", error: error.message });
            trace.push({ ...entry, status: "error", message: error.message });
        }
    }
}
