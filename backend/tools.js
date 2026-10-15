import { createCompanyResolver } from "./finance/resolve-company.js";
import { DateTime } from "luxon";
import { load } from "cheerio";
import { calculate } from "./calculator.js";
import { rememberSymbols } from "./memory.js";
import { FinanceMcpClient } from "./finance/client.js";
import { createWorkspace } from "./finance/workspace.js";

const headers = { "User-Agent": "APPS-Agent/1.0", Accept: "application/json" };
const companies = {
    apple: "AAPL", microsoft: "MSFT", google: "GOOGL", alphabet: "GOOGL", amazon: "AMZN",
    meta: "META", facebook: "META", tesla: "TSLA", nvidia: "NVDA", netflix: "NFLX",
    ibm: "IBM", intel: "INTC", amd: "AMD", oracle: "ORCL", adobe: "ADBE",
};

export function extractSymbols(raw = "", query = "") {
    const seed = `${raw} ${query}`;
    const known = (seed.toLowerCase().match(/[a-z]{3,}/g) || []).map((word) => companies[word]).filter(Boolean);
    if (/\btakes?[\s-]+(?:two|2)\s+interactive\b/i.test(seed)) known.push("TTWO");
    const explicit = seed.match(/\b[A-Z]{2,5}(?:\.[A-Z]{1,3})?\b/g) || [];
    return [...new Set([...known, ...explicit])];
}

export function extractDays(query) {
    const match = query.match(/(\d+)\s*(day|week)/i);
    return match ? Math.max(1, Number(match[1]) * (/week/i.test(match[2]) ? 7 : 1)) : 7;
}

export function quoteConversionTarget(query) {
    const match = query.match(/\b(?:convert|change|show|express|display)\s+(?:(?:that|it|this)(?:\s+(?:price|quote))?|(?:the\s+)?(?:last\s+|previous\s+)?(?:price|quote))\s+(?:to|in|into)\s+([a-z]{3})\b/i);
    const code = match?.[1].toUpperCase();
    return code && Intl.supportedValuesOf("currency").includes(code) ? code : null;
}

export function currentTime(timezone = "UTC") {
    const now = DateTime.now().setZone(timezone || "UTC");
    if (!now.isValid) throw new Error(`Unknown timezone '${timezone}'.`);
    return { timezone: now.zoneName, iso: now.toISO(), date: now.toISODate(), time: now.toFormat("HH:mm:ss"), weekday: now.toFormat("cccc") };
}

export function convertTime(timestamp, source = "UTC", target = "UTC") {
    const date = DateTime.fromISO(timestamp, { zone: source || "UTC", setZone: true }).setZone(source || "UTC");
    const converted = date.setZone(target || "UTC");
    if (!date.isValid || !converted.isValid) throw new Error("Invalid ISO timestamp or timezone.");
    return {
        source_timezone: date.zoneName, target_timezone: converted.zoneName,
        source_time: date.toISO(), converted_time: converted.toISO(),
        converted_display: converted.toFormat("yyyy-MM-dd HH:mm:ss ZZZZ"),
    };
}

export function createTools(fetcher = fetch, finance = new FinanceMcpClient()) {
    const workspace = createWorkspace(finance);
    const resolveCompany = createCompanyResolver(finance);
    async function request(endpoint, params = {}, text = false) {
        const url = new URL(endpoint);
        for (const [key, value] of Object.entries(params)) url.searchParams.set(key, String(value));
        const response = await fetcher(url, { headers, signal: AbortSignal.timeout(10000) });
        if (!response.ok) throw new Error(`${url.hostname} returned HTTP ${response.status}.`);
        return text ? response.text() : response.json();
    }

    async function stockHistory(symbol, days = 7) {
        const result = await finance.call("stock_history", { symbol, days });
        return result.history.map((row) => ({ ...row, currency: result.currency }));
    }

    async function lookupSymbols(raw, query) {
        const symbols = extractSymbols(raw, query);
        if (symbols.length) return symbols;
        const result = await finance.call("search_stocks", { query: `${raw || ""} ${query}`.trim() });
        return [...new Set(result.quotes.map((item) => item.symbol))];
    }

    async function weather(location) {
        const cleaned = location.split(/\n|###|System:|User:/)[0].trim().replace(/^[,. ]+|[,. ]+$/g, "");
        const candidates = [...new Set([cleaned, ...cleaned.split(",").map((part) => part.trim())])];
        let coordinates;
        for (const name of candidates.filter(Boolean)) {
            const data = await request("https://geocoding-api.open-meteo.com/v1/search", { name, count: 5, language: "en", format: "json" });
            const ranked = (data.results || []).map((item) => ({
                ...item, score: [[item.name, 3], [item.country, 2], [item.admin1, 1.5], [item.admin2, 1]]
                    .reduce((score, [value, weight]) => score + (value && cleaned.toLowerCase().includes(value.toLowerCase()) ? weight : 0), Math.min((item.population || 0) / 1000000, 1)),
            }));
            for (const item of ranked) if (!coordinates || item.score > coordinates.score) coordinates = item;
        }
        if (!coordinates) throw new Error(`Unable to find coordinates for '${location}'.`);
        const data = await request("https://api.open-meteo.com/v1/forecast", {
            latitude: coordinates.latitude, longitude: coordinates.longitude, current_weather: true, timezone: coordinates.timezone || "auto",
        });
        if (!data.current_weather) throw new Error("Weather API did not return current conditions.");
        const current = data.current_weather;
        return {
            location: { name: coordinates.name, country: coordinates.country, latitude: coordinates.latitude, longitude: coordinates.longitude },
            weather: { temperature_c: current.temperature, windspeed_kmh: current.windspeed, winddirection: current.winddirection, time: current.time, weathercode: current.weathercode },
        };
    }

    async function factLookup(topic) {
        const data = await request("https://api.duckduckgo.com/", { q: topic, format: "json", no_html: 1, skip_disambig: 1 });
        if (data.AbstractText || data.Abstract) return { answer: data.AbstractText || data.Abstract, source: data.AbstractSource || "DuckDuckGo", url: data.AbstractURL };
        const html = await request("https://duckduckgo.com/html/", { q: topic }, true);
        const $ = load(html);
        const stopwords = new Set("what when who whom that this with your from have been will into about there their where which would could should does are can for some only than then were much".split(" "));
        const keywords = [...new Set(topic.toLowerCase().match(/[a-z]{2,}/g) || [])].filter((word) => !stopwords.has(word)).slice(0, 4);
        const results = $(".result").toArray().map((element) => {
            const link = $(element).find(".result__a");
            const answer = $(element).find(".result__snippet").text().trim();
            const source = link.text().trim();
            const url = new URL(link.attr("href") || "/", "https://duckduckgo.com");
            return { answer, source, url: url.searchParams.get("uddg") || url.href,
                score: keywords.filter((word) => `${source} ${answer}`.toLowerCase().includes(word)).length };
        }).filter((item) => item.answer && item.score).sort((a, b) => b.score - a.score);
        if (!results.length) throw new Error(`No instant answer available for '${topic}'.`);
        return results[0];
    }

    async function execute(decision, query, memory, refine) {
        switch (decision.tool_choice) {
            case "resolve_company": return JSON.stringify(await resolveCompany({ name: decision.company_name, country: decision.company_country }));
            case "finance_workspace": {
                const report = await workspace.run(JSON.parse(decision.workspace_arguments));
                const profile = report.data?.profile;
                const title = report.workflow === "research" && profile ? `Company research report for ${profile.name || profile.symbol} (${profile.symbol})` : `${report.workflow} report`;
                return { answer: `${title} generated from Yahoo Finance data.${report.warnings.length ? ` ${report.warnings.length} data-availability notices; see the report for limitations.` : ""}`, report };
            }
            case "finance_data": {
                let args;
                try { args = JSON.parse(decision.finance_arguments); }
                catch { return "I could not interpret the finance arguments. Please specify the ticker and dataset."; }
                if (!args || typeof args !== "object" || Array.isArray(args)) return "Finance arguments must be an object.";
                const data = await finance.call(decision.finance_tool, args);
                return `${data.source} (retrieved ${data.retrieved_at}${data.truncated ? "; output truncated" : ""}):\n${JSON.stringify(data.data, null, 2)}`;
            }
            case "currency_convert": {
                const quote = memory.stock_context.last_quote;
                if (!quote) return "Please request a stock quote first so I know which price to convert.";
                const target = (decision.target_currency || "").trim().toUpperCase();
                if (!/^[A-Z]{3}$/.test(target)) return "Specify a target currency code, such as GBP.";
                if (target === quote.currency) return `${quote.symbol}: ${quote.price.toFixed(2)} ${target} (already in ${target}; stock data as of ${quote.date}).`;
                // Yahoo can label UK share prices in pence rather than pounds.
                const source = quote.currency === "GBp" || quote.currency === "GBX" ? "GBP" : quote.currency.toUpperCase();
                const amount = quote.currency === "GBp" || quote.currency === "GBX" ? quote.price / 100 : quote.price;
                const fx = source === target ? { rate: 1, date: quote.date, source: "Pence-to-pounds conversion" } : await finance.call("exchange_rate", { from_currency: source, to_currency: target });
                const price = new Intl.NumberFormat("en-GB", { style: "currency", currency: target }).format(amount * fx.rate);
                return `${quote.symbol}: approximately ${price} ${target}, converted from ${quote.price.toFixed(2)} ${quote.currency}. Stock data as of ${quote.date}; FX rate ${fx.rate} ${target} per ${source} as of ${fx.date} (${fx.source}). Reference conversion; excludes fees.`;
            }
            case "calculator": {
                if (!decision.calculator_expression) return "Provide a math expression for me to calculate.";
                return `${decision.calculator_expression} = ${calculate(decision.calculator_expression)}`;
            }
            case "weather": {
                if (!decision.location) return "I need a specific city or region to check the weather.";
                const result = await weather(decision.location);
                Object.assign(memory.weather_context, { last_location: result.location, last_conditions: result.weather, last_updated: new Date().toISOString() });
                return `It is currently ${result.weather.temperature_c}°C in ${result.location.name}, ${result.location.country} with winds at ${result.weather.windspeed_kmh} km/h.`;
            }
            case "topic_summary": {
                if (!decision.topic) return "Please tell me which topic you'd like summarized.";
                const data = await request(`https://en.wikipedia.org/api/rest_v1/page/summary/${encodeURIComponent(decision.topic.replaceAll(" ", "_"))}`);
                if (!data.extract || data.type === "disambiguation") throw new Error("No unambiguous summary available; try a more specific topic.");
                return `${data.title}: ${data.extract} (${data.content_urls?.desktop?.page || ""})`;
            }
            case "news": {
                if (!decision.news_query) return "Let me know the keywords or company you want news about.";
                const data = await request("https://hn.algolia.com/api/v1/search", { query: decision.news_query, tags: "story", hitsPerPage: 3, restrictSearchableAttributes: "title" });
                if (!data.hits?.length) throw new Error("No tech news results found.");
                return "Latest headlines:\n- " + data.hits.map((item) => `${item.title || item.story_title} (${item.url || item.story_url || "link unavailable"})`).join("\n- ");
            }
            case "news_api": {
                const data = await request("https://www.reddit.com/search.json", { q: decision.news_query || query, sort: "new", limit: 5, type: "link" });
                const posts = data.data?.children || [];
                if (!posts.length) throw new Error("No articles found.");
                return "Top articles:\n- " + posts.map(({ data: item }) => `${item.title} - r/${item.subreddit} (${item.url})`).join("\n- ");
            }
            case "time_now": {
                const result = currentTime(decision.time_timezone);
                memory.time_context.last_timezone_request = result.timezone;
                memory.time_context.last_time_result = result;
                return `The current time in ${result.timezone} is ${result.date} ${result.time} (${result.weekday}).`;
            }
            case "time_convert": {
                const result = convertTime(decision.convert_timestamp, decision.convert_from_timezone, decision.convert_to_timezone);
                memory.time_context.last_conversion = result;
                return `${result.converted_display} (from ${result.source_time})`;
            }
            case "fact_lookup": {
                const topic = decision.fact_topic || decision.topic || query;
                const fact = await factLookup(topic);
                memory.fact_context.recent_facts = [...memory.fact_context.recent_facts, { topic, ...fact, timestamp: new Date().toISOString() }].slice(-10);
                const answer = await refine(`Source: ${fact.source}\nURL: ${fact.url}\nSnippet: ${fact.answer}`);
                return `${answer || fact.answer}${fact.url ? ` (${fact.url})` : ""}`;
            }
            case "stock_quote": {
                const symbols = await lookupSymbols(decision.stock_symbol, query);
                const symbol = symbols[0] || memory.stock_context.recent_symbols.at(-1);
                if (!symbol) return "Specify at least one stock ticker or company name.";
                const quote = await finance.call("stock_quote", { symbol });
                rememberSymbols(memory, [quote.symbol]);
                memory.stock_context.last_quote = quote;
                const change = quote.change === null ? "change unavailable" : `change ${quote.change.toFixed(2)} / ${quote.percent_change === null ? "unavailable" : `${quote.percent_change.toFixed(2)}%`}`;
                return `${quote.symbol}: ${quote.price.toFixed(2)} ${quote.currency} (${change}). ${quote.source} daily data as of ${quote.date}.`;
            }
            case "crypto_price": {
                if (!decision.crypto_asset) return "Specify a cryptocurrency identifier, such as bitcoin.";
                const asset = decision.crypto_asset.toLowerCase(), currency = (decision.crypto_currency || "usd").toLowerCase();
                const data = await request("https://api.coingecko.com/api/v3/simple/price", { ids: asset, vs_currencies: currency });
                if (data[asset]?.[currency] == null) throw new Error(`Coin '${asset}' not found on CoinGecko.`);
                return `${asset}: ${data[asset][currency]} ${currency.toUpperCase()} (CoinGecko).`;
            }
            case "holiday_lookup": {
                const country = (decision.holiday_country || "GB").toUpperCase();
                const year = Number(decision.holiday_year || new Date().getUTCFullYear());
                const month = decision.holiday_month ? Number(decision.holiday_month) : null;
                if (!Number.isInteger(year) || (month !== null && (!Number.isInteger(month) || month < 1 || month > 12))) throw new Error("Invalid holiday year or month.");
                const data = await request(`https://date.nager.at/api/v3/PublicHolidays/${year}/${encodeURIComponent(country)}`);
                const today = new Date().toISOString().slice(0, 10);
                const holidays = data.filter((item) => item.date >= today && (!month || Number(item.date.slice(5, 7)) === month)).sort((a, b) => a.date.localeCompare(b.date)).slice(0, 5);
                return holidays.length ? "Upcoming holidays:\n- " + holidays.map((item) => `${item.date}: ${item.localName} (${(item.types || []).join(", ")})`).join("\n- ") : "No upcoming holidays found.";
            }
            case "fun_activity": {
                const data = await request("https://www.boredapi.com/api/activity");
                if (!data.activity) throw new Error("Activity service unavailable.");
                return `Try this activity: ${data.activity} (type: ${data.type}, participants: ${data.participants}).`;
            }
            case "fun_joke": {
                let data = await request("https://v2.jokeapi.dev/joke/Any", decision.fun_topic ? { contains: decision.fun_topic } : {});
                if (data.error && decision.fun_topic) data = await request("https://v2.jokeapi.dev/joke/Any");
                if (data.error) throw new Error(data.message || "Joke lookup failed.");
                return `${data.category} joke:\n${data.type === "single" ? data.joke : `${data.setup}\n${data.delivery}`}`;
            }
            default: return null;
        }
    }
    return {
        execute, stockHistory, lookupSymbols, resolveCompany,
        financeCall: (name, args) => finance.call(name, args),
        financeCatalog: async () => {
            await finance.connect();
            return finance.tools.map(({ name, description, inputSchema }) => ({ name, description, inputSchema }));
        },
    };
}
