import { createChains, routingSchema, answerSchema, followupSchema, financePlanSchema, workspacePlanSchema, toolCatalog, rewriteSchema, applicationToolSchema } from "./llm.js";
import { getModelName } from "./llm.js";
import { runAgentLoop, loopStepSchema } from "./agent-loop.js";
import { companyRequest } from "./finance/resolve-company.js";
import { workspaceRequest, tableRecords } from "./finance/workspace.js";
import { packageTools } from "./finance/client.js";
import { createMemory, rememberComparison, rememberSymbols } from "./memory.js";
import { createTools, extractDays, extractSymbols, quoteConversionTarget } from "./tools.js";
import { tradingInputs, tradingDescriptions } from "./trading/client.js";
import { createToolContext, toolSearchInput } from "./context.js";

const signed = (value) => `${value >= 0 ? "+" : ""}${value.toFixed(2)}`;
const broadMarket = (query) => /\b(?:stock market|market overview|market brief|market benchmarks)\b/i.test(query)
    && /\b(?:today|now|doing|overview|brief|benchmarks|latest|snapshot)\b/i.test(query)
    && !/\b(?:explain|what is|how does|history of|compare|yesterday|tomorrow|last|ago|\d{4}|UK|British|London|FTSE|European|Europe|Asian|Asia|Japan|China|India)\b/i.test(query);
const contextualReply = (query) => /^(?:surprise me|you (?:choose|pick)|go ahead|yes|please do|try again)$/i.test(query.trim());
const needsRewrite = (query) => contextualReply(query) || /\b(?:that|those|it|them|same|instead|what about|how about|now in)\b/i.test(query);
const estimateTokens = (text) => text ? Math.max(1, Math.floor(text.length / 4)) : 0;

export function comparisonSummary(entries, days) {
    const sorted = [...entries].sort((a, b) => b.change_pct - a.change_pct);
    const best = sorted[0], worst = sorted.at(-1);
    return `Over the last ${days} days, ${best.symbol} outperformed ${worst.symbol} by ${(best.change_pct - worst.change_pct).toFixed(2)} percentage points (${signed(best.change_pct)}% vs ${signed(worst.change_pct)}%).`;
}

export function createAgent({ chains = createChains(), tools = createTools(), store, trading } = {}) {
    async function run(query, metadata = {}) {
        if (typeof query !== "string" || !query.trim()) throw new Error("Query cannot be empty.");
        const started = performance.now();
        const memory = createMemory(metadata);
        const session = String(metadata.session_id || metadata.conversation_id || metadata.session || "default");
        const timings = {}, usage = {}, matches = [], traces = [];
        const reports = new Map();
        const tradingJobs = new Map();
        const rewrites = [], toolErrors = [], loopTraces = [];
        const tokens = { calls: 0, prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 };
        async function profile(name, work) {
            const start = performance.now();
            try { return await work(); }
            finally {
                const stats = timings[name] ||= { count: 0, total_ms: 0, avg_ms: 0 };
                stats.count++;
                stats.total_ms += performance.now() - start;
                stats.avg_ms = stats.total_ms / stats.count;
            }
        }
        async function call(name, chain, schema, input) {
            const result = await profile(name, async () => schema.parse(await chain.invoke(input)));
            tokens.calls++;
            tokens.prompt_tokens += estimateTokens(JSON.stringify(input));
            tokens.completion_tokens += estimateTokens(JSON.stringify(result));
            tokens.total_tokens = tokens.prompt_tokens + tokens.completion_tokens;
            return result;
        }
        async function compare(symbols, days) {
            const entries = [];
            for (const symbol of symbols) {
                usage.stock_history = (usage.stock_history || 0) + 1;
                const history = await profile("tool_stock_history", () => tools.stockHistory(symbol, days));
                const start = history[0].close, end = history.at(-1).close;
                entries.push({ symbol, start, end, change_pct: start ? (end - start) / start * 100 : 0 });
            }
            rememberComparison(memory, entries, days);
            const best = [...entries].sort((a, b) => b.change_pct - a.change_pct)[0];
            const reflection = `Keep an eye on ${best.symbol} after its ${signed(best.change_pct)}% move.`;
            memory.user_profile.reminders.push({ text: reflection, metadata: { source: "stock_compare", symbols, days }, timestamp: new Date().toISOString() });
            traces.push({
                planner: "stock_compare", goal: `Compare ${symbols.slice(0, 2).join(", ")}`,
                steps: [...symbols.map((symbol) => ({ action: "fetch_stock_history", symbol, description: `Fetch ${symbol} history for ${days} days` })), { action: "compare", description: "Analyze performance and summarize winner" }],
                reflection, outcome: { best: best.symbol, worst: [...entries].sort((a, b) => a.change_pct - b.change_pct)[0].symbol, days },
            });
            return "Stock comparison:\n- " + entries.map((entry) => `${entry.symbol}: ${entry.start.toFixed(2)} -> ${entry.end.toFixed(2)} (${signed(entry.change_pct)}% over ${days}d)`).join("\n- ") + `\n${comparisonSummary(entries, days)}\n\nReflection: ${reflection}`;
        }
        function toolFailure(name, error) {
            toolErrors.push({ tool: name, message: error.message });
            const finance = /^(?:stock|finance|currency)/.test(name);
            return finance
                ? "I couldn’t retrieve the requested market data right now. You can say ‘try again’, ask for a company research brief, or ask me to explain how the market benchmarks work. I won’t estimate unavailable prices."
                : "I couldn’t reach the data service for that request. You can say ‘try again’ or ask a related question that does not need live data.";
        }
        async function answer(originalSegment) {
            let segment = originalSegment;
            const timezone = metadata.user_profile?.timezone || "Europe/London";
            const referenceDate = new Intl.DateTimeFormat("en-CA", { timeZone: timezone }).format(new Date());
            const recentMessages = store?.recent(session, 6) || [];
            const context = memory.conversation_context;
            const lastQuery = context.last_effective_query || [...recentMessages].reverse().find((item) => item.role === "user")?.content || "";
            if (contextualReply(segment) && broadMarket(lastQuery)) segment = "Give me an on-demand US stock market benchmark brief";
            else if (/^try again$/i.test(segment) && lastQuery) segment = lastQuery;
            else if (!quoteConversionTarget(segment) && needsRewrite(segment) && (lastQuery || recentMessages.length) && chains.rewrite) {
                try {
                    const rewritten = await call("lm_query_rewrite", chains.rewrite, rewriteSchema, {
                        query: segment, conversation: JSON.stringify({ last_query: lastQuery, messages: recentMessages.slice(-6) }), reference_date: referenceDate, timezone,
                    });
                    if (rewritten.clarification) return rewritten.clarification;
                    segment = rewritten.query;
                } catch { /* Preserve the original query when rewriting is unavailable. */ }
            }
            if (segment !== originalSegment) rewrites.push({ original: originalSegment, rewritten: segment });
            memory.conversation_context = { last_query: originalSegment, last_effective_query: segment, last_tool: "" };
            const recalled = await profile("semantic_lookup", () => store?.query(session, segment) || []);
            if (recalled.length) matches.push({ query: segment, matches: recalled });
            let routedQuery = segment;
            if (recentMessages.length) routedQuery += `\n\nRecent conversation:\n${recentMessages.map((item) => `${item.role}: ${item.content}`).join("\n")}`;
            if (recalled.length) routedQuery += `\n\nRelevant prior messages:\n${recalled.map((item) => `${item.role}: ${item.content}`).join("\n")}`;
            // Discover detailed finance schemas only when the router selects the package tools.
            const conversionTarget = quoteConversionTarget(segment);
            const researchSymbols = /\b(?:company\s+research|research\s+(?:brief|report))\b/i.test(segment) ? extractSymbols("", segment) : [];
            const researchRequest = researchSymbols.length === 1 ? { workflow: "research", symbol: researchSymbols[0] } : null;
            const marketRequest = broadMarket(segment) ? { workflow: "morning", date: referenceDate, timezone, watchlist: [] } : null;
            const directWorkspace = marketRequest || researchRequest;
            if (chains.loop) {
                const companyBrief = /\b(?:brief|research|report)\b/i.test(segment) && /\b(?:company|corporation)\b/i.test(segment) && !/\bcompare|comparison\b/i.test(segment);
                const applications = (companyBrief ? ["resolve_company", "finance_workspace"] : Object.keys(toolCatalog)).filter((name) => !["none", "finance_data"].includes(name));
                const mcpNames = companyBrief ? ["search_stocks", "lookup_instruments", "ticker_data"] : ["search_stocks", "stock_history", "stock_quote", "exchange_rate", ...packageTools];
                const available = new Set([...applications, ...mcpNames.map((name) => `mcp.${name}`)]);
                if (trading && !companyBrief) for (const name of Object.keys(tradingInputs)) available.add(name);
                let catalog = null;
                const toolMetadata = [...available].map(name => ({ name,
                    keywords: ({ trading_start: 'demo simulate simulation backtest replay watch', calculator: 'calculate multiply divide add subtract numbers' })[name] || '',
                    description:
                    Object.hasOwn(tradingInputs, name) ? tradingDescriptions[name] : name.startsWith('mcp.') ?
                        ({ search_stocks: 'Search Yahoo company stocks by name and country',
                            ticker_data: 'Yahoo company metadata financial statements news dividends estimates holders',
                            search_finance: 'Search Yahoo Finance news headlines quotes and companies',
                            lookup_instruments: 'Find company stock listings by name category and exchange',
                        }[name.slice(4)] || `Yahoo Finance ${name.slice(4).replaceAll('_', ' ')}`) :
                        toolCatalog[name] + (name === 'finance_workspace' ? ' Yahoo market news headlines today.' : ''),
                }));
                const toolContext = createToolContext(toolMetadata, async entry => {
                    const name = entry.name;
                    if (Object.hasOwn(tradingInputs, name)) return { ...entry, input_schema: tradingInputs[name].toJSONSchema({ io: 'input' }) };
                    if (name.startsWith('mcp.')) {
                        catalog ||= await tools.financeCatalog();
                        const definition = catalog.find(item => item.name === name.slice(4));
                        if (!definition) throw new Error(`MCP tool ${name} is unavailable.`);
                        return { ...entry, input_schema: definition.inputSchema };
                    }
                    return { ...entry, input_schema: name === 'resolve_company' ? companyRequest.toJSONSchema({ io: 'input' }) :
                        name === 'finance_workspace' ? workspaceRequest.toJSONSchema({ io: 'input' }) : applicationToolSchema(name) };
                });
                toolContext.search(segment);
                available.add('tool_search');
                let searchScope = [...available];
                const inspectedCompanies = new Set();
                const candidates = new Map();
                function plannerTools(observations) {
                    let names = [...available];
                    if (observations.some((item) => item.status === "ok" && ["trading_start", "trading_stop", "trading_dataset_create", "trading_experiment_start", "trading_experiment_cancel", "trading_daily_research_start", "trading_sector_research_start", "trading_weekly_research_start"].includes(item.tool))) return [];
                    if (companyBrief) {
                        const lastSuccess = [...observations].reverse().find((item) => item.status === "ok");
                        if (lastSuccess?.tool === "finance_workspace") names = [];
                        else if (lastSuccess?.tool === "resolve_company") names = lastSuccess.result?.status === "resolved" ? ["finance_workspace"] : [];
                        else if (lastSuccess?.tool === "mcp.ticker_data" && inspectedCompanies.size) names = ["finance_workspace", "mcp.search_stocks", "mcp.lookup_instruments"];
                        else if (!candidates.size) names = ["resolve_company"];
                        else names = ["mcp.search_stocks", "mcp.lookup_instruments", "mcp.ticker_data"];
                    }
                    return names;
                }
                const loop = await runAgentLoop({
                    availableTools: available, requireReport: companyBrief,
                    finishOnReport: companyBrief || Boolean(marketRequest) ||
                        (/\b(?:news|brief|report|overview|dashboard)\b/i.test(segment) &&
                            !/\b(?:and|also|then|plus|after|explain|analyse|analyze|interpret)\b|[,;]/i.test(segment)),
                    seed: marketRequest ? { action: "tool", tool: "finance_workspace", arguments: marketRequest } : conversionTarget ? { action: "tool", tool: "currency_convert", arguments: { target_currency: conversionTarget } } : null,
                    choose: async (observations, remaining) => {
                        const permitted = plannerTools(observations);
                        searchScope = permitted;
                        const packet = await toolContext.packet(permitted, companyBrief ? permitted : []);
                        const descriptors = companyBrief ? packet.tools.filter(tool => tool.name !== 'tool_search') : packet.tools;
                        const names = descriptors.map(tool => tool.name);
                        return call("lm_loop_decision", chains.loop, loopStepSchema, {
                            query: segment, context: JSON.stringify({ recent_messages: recentMessages, memory, company_candidates: [...candidates.values()], inspected_symbols: [...inspectedCompanies], unavailable_tools: packet.unavailable }), reference_date: referenceDate, timezone,
                            allowed_tools: names, allowed_actions: companyBrief && !observations.length ? ["tool", "clarify"] : names.length ? ["tool", "finish", "clarify"] : ["finish", "clarify"], available_tools: JSON.stringify(descriptors), observations: JSON.stringify(observations), remaining_steps: remaining,
                        });
                    },
                    execute: async (name, args) => {
                        memory.conversation_context.last_tool = name;
                        usage[name] = (usage[name] || 0) + 1;
                        return profile(`tool_${name}`, async () => {
                            if (name === 'tool_search') return {
                                tools: toolContext.search(toolSearchInput.parse(args).query, searchScope),
                                note: 'Matching schemas are loaded for your next decision. Search a different capability or exact tool name if needed.',
                            };
                            if (Object.hasOwn(tradingInputs, name)) {
                                const result = await trading.call(name, tradingInputs[name].parse(args));
                                if (result.id) {
                                    memory.conversation_context.last_trading_job_id = result.id;
                                    tradingJobs.set(originalSegment, { id: result.id, status: result.status, dashboard_url: result.dashboard_url });
                                }
                                return result;
                            }
                            if (name === "resolve_company") {
                                const result = await tools.resolveCompany(companyRequest.parse(args));
                                if (result.status === "resolved") {
                                    candidates.set(result.company.symbol.toUpperCase(), result.company);
                                    inspectedCompanies.add(result.company.symbol.toUpperCase());
                                }
                                return result;
                            }
                            if (name.startsWith("mcp.")) {
                                const toolName = name.slice(4);
                                catalog ||= await tools.financeCatalog();
                                const definition = catalog.find((item) => item.name === toolName);
                                if (!definition) throw new Error(`MCP tool ${toolName} is unavailable.`);
                                if (companyBrief && toolName === "ticker_data" && !candidates.has(String(args.symbol).toUpperCase())) throw new Error("This ticker was not returned by company discovery. An empty search does not verify a raw acronym. Try a full company name or lookup_instruments category stock first.");
                                const result = await tools.financeCall(toolName, args);
                                if (toolName === "search_stocks" || toolName === "lookup_instruments") {
                                    const listings = toolName === "search_stocks" ? result.quotes : tableRecords(result.data).map((row) => ({ symbol: row.index, name: row.shortName, exchange: row.exchange }));
                                    for (const listing of listings || []) if (typeof listing.symbol === "string") candidates.set(listing.symbol.toUpperCase(), listing);
                                }
                                if (toolName === "stock_quote") {
                                    memory.stock_context.last_quote = result;
                                    rememberSymbols(memory, [result.symbol]);
                                }
                                if (toolName === "ticker_data" && args.dataset === "info" && (result.data?.longName || result.data?.shortName)) inspectedCompanies.add(String(args.symbol).toUpperCase());
                                return result;
                            }
                            if (name === "finance_workspace" && ["research", "earnings", "comparison"].includes(args.workflow)) {
                                const symbols = args.symbols || [args.symbol];
                                if (symbols.some((symbol) => !inspectedCompanies.has(String(symbol).toUpperCase()))) throw new Error("Company identity has not been inspected. Fetch mcp.ticker_data with dataset info for each requested symbol and confirm its name/country before generating this report.");
                            }
                            const decision = routingSchema.parse({ ...args, tool_choice: name,
                                ...(name === "finance_workspace" ? { workspace_arguments: JSON.stringify(workspaceRequest.parse(args)) } : {}),
                            });
                            const result = await tools.execute(decision, segment, memory, async (context) =>
                                (await call("lm_tool_refiner", chains.refiner, answerSchema, { query: segment, context })).answer);
                            if (result === null) throw new Error("Tool returned no evidence.");
                            return result;
                        });
                    },
                });
                loopTraces.push({ query: originalSegment, stop_reason: loop.stop_reason, steps: loop.trace });
                for (const observation of loop.observations.filter((item) => item.status === "error")) toolErrors.push({ tool: observation.tool, message: observation.error });
                if (loop.report) reports.set(originalSegment, loop.report);
                if (!loop.observations.length && loop.stop_reason === "complete") usage.direct_response = (usage.direct_response || 0) + 1;
                return loop.answer;
            }
            const decision = directWorkspace ? routingSchema.parse({ tool_choice: "finance_workspace" }) : conversionTarget ? routingSchema.parse({ tool_choice: "currency_convert", target_currency: conversionTarget }) : await call("lm_router", chains.router, routingSchema, {
                query: routedQuery, available_tools: Object.entries(toolCatalog).map(([key, value]) => `- ${key}: ${value}`).join("\n"),
            });
            memory.conversation_context.last_tool = decision.tool_choice;
            if (decision.tool_choice === "finance_workspace") {
                const planned = directWorkspace ? { request: directWorkspace, clarification: "" } : await call("lm_workspace_arguments", chains.workspace, workspacePlanSchema, {
                    query: routedQuery,
                    reference_date: new Intl.DateTimeFormat("en-CA", { timeZone: timezone }).format(new Date()), timezone,
                });
                if (!planned.request) return planned.clarification || "Please specify the company or holdings for this report.";
                decision.workspace_arguments = JSON.stringify(planned.request);
            }
            if (decision.tool_choice === "finance_data" && tools.financeCatalog) {
                const catalog = await tools.financeCatalog();
                const options = catalog.filter((tool) => packageTools.includes(tool.name));
                const selected = options.find((tool) => tool.name === decision.finance_tool);
                const planned = await call("lm_finance_arguments", chains.finance, financePlanSchema, {
                    query: routedQuery,
                    available_tools: JSON.stringify(selected ? [selected] : options),
                });
                decision.finance_tool = planned.name;
                decision.finance_arguments = JSON.stringify(planned.arguments);
            }
            const previous = memory.stock_context.last_comparison;
            const recent = memory.stock_context.recent_symbols;
            let followup = false;
            if (!["currency_convert", "finance_data", "finance_workspace"].includes(decision.tool_choice) && (previous || recent.length)) {
                const intent = await call("lm_followup_intent", chains.followup, followupSchema, {
                    previous_summary: JSON.stringify({ comparison: previous, recent_symbols: recent }), query: segment,
                });
                followup = intent.refers_to_stock_comparison === "Yes";
            }
            if (followup && decision.tool_choice !== "stock_quote" && previous?.entries?.length >= 2) {
                return comparisonSummary(previous.entries, previous.days);
            }
            if (!["finance_data", "finance_workspace"].includes(decision.tool_choice) && (decision.tool_choice === "stock_quote" || /\bcompare\b/i.test(segment) || followup)) {
                try {
                    let symbols = await tools.lookupSymbols(decision.stock_symbol, segment);
                    if (!symbols.length) symbols = recent.slice(-2);
                    if (symbols.length > 1) return await compare(symbols.slice(0, 4), extractDays(segment));
                } catch (error) { return toolFailure("stock_quote", error); }
            }
            if (decision.tool_choice !== "none") {
                const name = decision.tool_choice;
                usage[name] = (usage[name] || 0) + 1;
                try {
                    const result = await profile(`tool_${name}`, () => tools.execute(decision, segment, memory, async (context) => {
                        return (await call("lm_tool_refiner", chains.refiner, answerSchema, { query: segment, context })).answer;
                    }));
                    if (result?.report) { reports.set(originalSegment, result.report); return result.answer; }
                    if (result !== null) return result;
                } catch (error) { return toolFailure(name, error); }
            }
            usage.direct_response = (usage.direct_response || 0) + 1;
            return decision.direct_answer || (await call("lm_general_answer", chains.general, answerSchema, { query: segment })).answer;
        }
        // Split sentence boundaries without breaking decimal numbers or ticker suffixes.
        const segments = query.split(/[?!]+|\.(?=\s|$)/).map((part) => part.trim()).filter(Boolean);
        const responses = [];
        for (const segment of segments.length ? segments : [query.trim()]) {
            const result = await profile("segment_pipeline", () => answer(segment));
            await profile("semantic_store_write", () => {
                store?.addEntry(session, "user", segment);
                store?.addEntry(session, "assistant", result);
            });
            responses.push({ query: segment, answer: result, ...(reports.has(segment) ? { report: reports.get(segment) } : {}), ...(tradingJobs.has(segment) ? { trading_job: tradingJobs.get(segment) } : {}) });
        }
        const enriched = { ...memory, session_id: session, timings };
        if (loopTraces.length) enriched.agent_trace = loopTraces;
        if (rewrites.length) enriched.query_rewrites = rewrites;
        if (toolErrors.length) enriched.tool_errors = toolErrors;
        if (matches.length) enriched.semantic_matches = matches;
        if (traces.length) enriched.plan_trace = traces;
        return {
            answer: responses.map((item) => metadata.response_mode === "api" ? item.answer : `For "${item.query}": ${item.answer}`).join("\n\n"),
            responses, usage, token_usage: tokens, metadata: enriched,
            latency_ms: Math.round((performance.now() - started) * 100) / 100, timings,
            model: getModelName(),
        };
    }
    return { run };
}
