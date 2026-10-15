import { z } from "zod";
import { tableRecords } from "./workspace.js";

export const companyRequest = z.object({ name: z.string().trim().min(1).max(120), country: z.string().trim().max(80).default("") });
const normalize = (value) => String(value || "").toLowerCase().normalize("NFKD").replace(/[^\p{L}\p{N}]/gu, "");
const companyName = (value) => normalize(String(value || "").replace(/\b(?:incorporated|inc|corporation|corp|limited|ltd|plc|company|co|jsc)\b\.?/gi, ""));
const symbolMatches = (symbol, name) => normalize(symbol) === normalize(name) || normalize(symbol.split(".")[0]) === normalize(name);
const countryName = (value) => ({ us: "unitedstates", usa: "unitedstates", uk: "unitedkingdom", gb: "unitedkingdom", vn: "vietnam" })[normalize(value)] || normalize(value);

export function createCompanyResolver(finance) {
    return async function resolve(input) {
        const request = companyRequest.parse(input);
        const candidates = new Map(), attempts = [], errors = [];
        async function call(tool, args) {
            try {
                const result = await finance.call(tool, args);
                attempts.push({ tool, arguments: args, status: "ok" });
                return result;
            } catch (error) {
                attempts.push({ tool, arguments: args, status: "error" });
                errors.push({ tool, message: error.message });
                return null;
            }
        }
        function collect(listings) {
            for (const listing of listings || []) if (typeof listing.symbol === "string") candidates.set(listing.symbol, listing);
        }
        const search = await call("search_stocks", { query: request.name });
        collect(search?.quotes);
        if (!candidates.size) {
            const lookup = await call("lookup_instruments", { query: request.name, category: "stock", limit: 10 });
            collect(tableRecords(lookup?.data).map((row) => ({ symbol: row.index, name: row.shortName, exchange: row.exchange })));
        }
        if (!candidates.size && !/\b(?:corporation|corp|inc|ltd|plc)\b/i.test(request.name)) {
            const expanded = await call("search_stocks", { query: `${request.name} Corporation` });
            collect(expanded?.quotes);
        }
        const name = companyName(request.name);
        const ranked = [...candidates.values()].map((item) => ({ ...item,
            score: companyName(item.name) === name ? 3 : symbolMatches(item.symbol, request.name) ? 2 : companyName(item.name).startsWith(name) ? 1 : 0,
        })).filter((item) => item.score > 0).sort((a, b) => b.score - a.score);
        const verified = [], unverified = [];
        // Each resolver action performs at most three discovery calls and three metadata calls.
        for (const listing of ranked.slice(0, 3)) {
            const profile = await call("ticker_data", { symbol: listing.symbol, dataset: "info" });
            const info = profile?.data;
            const fullName = info?.longName || info?.shortName;
            if (!fullName) { unverified.push({ ...listing, reason: "Company metadata unavailable" }); continue; }
            const matchesName = companyName(fullName) === name || companyName(fullName).startsWith(name) || symbolMatches(listing.symbol, request.name);
            const matchesSymbol = !info.symbol || normalize(info.symbol) === normalize(listing.symbol);
            const matchesCountry = !request.country || (info.country && countryName(info.country) === countryName(request.country));
            const identity = { symbol: listing.symbol, name: fullName, country: info.country || null, exchange: info.exchange || listing.exchange,
                currency: info.currency || null, source_url: `https://finance.yahoo.com/quote/${encodeURIComponent(listing.symbol)}/profile/`,
                source: profile.source, retrieved_at: profile.retrieved_at, score: listing.score };
            if (matchesName && matchesCountry && matchesSymbol) verified.push(identity);
            else unverified.push({ ...identity, reason: !matchesSymbol ? "Provider symbol differs" : !matchesName ? "Company name differs" : info.country ? "Country differs" : "Country metadata unavailable" });
        }
        const exact = verified.filter((item) => companyName(item.name) === name);
        const matches = exact.length ? exact : verified;
        const uninspected = ranked.slice(3);
        const uncertainUnique = matches.length === 1 && uninspected.some((item) => item.score >= matches[0].score);
        unverified.push(...uninspected.map((item) => ({ ...item, reason: "Metadata inspection budget reached" })));
        const status = uncertainUnique ? "ambiguous" : matches.length === 1 ? "resolved" : matches.length > 1 ? "ambiguous" : errors.length ? "unavailable" : "not_found";
        return { status, request, ...(status === "resolved" ? { company: matches[0] } : {}), candidates: matches,
            unverified_candidates: unverified, attempts, errors, source: "Yahoo Finance via yfinance MCP",
            limitation: ranked.length > 3 ? "Only the three highest-ranked candidates were inspected; other listings may exist." : null };
    };
}
