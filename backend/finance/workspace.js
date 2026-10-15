import { z } from "zod";

const symbol = z.string().trim().min(1).max(20).regex(/^[A-Za-z0-9^][A-Za-z0-9.^=\-]*$/).transform((value) => value.toUpperCase());
const symbols = z.array(symbol).min(2).max(4).refine((values) => new Set(values).size === values.length, "Use distinct symbols");
const currency = z.string().trim().regex(/^[A-Za-z]{3}$/).transform((value) => value.toUpperCase());
export const workspaceRequest = z.discriminatedUnion("workflow", [
    z.object({ workflow: z.literal("research"), symbol }),
    z.object({ workflow: z.literal("comparison"), symbols, period: z.enum(["1mo", "3mo", "6mo", "1y"]).default("3mo") }),
    z.object({ workflow: z.literal("earnings"), symbol }),
    z.object({ workflow: z.literal("overlap"), symbols: symbols.refine((values) => values.length === 2, "Choose two ETFs") }),
    z.object({ workflow: z.literal("screener"), sector: z.enum(["Technology", "Healthcare", "Financial Services", "Industrials", "Consumer Cyclical"]).default("Technology"), max_pe: z.number().positive().max(200).default(30), max_debt_equity: z.number().nonnegative().max(1000).default(100).describe("Debt/equity percentage; 100 means debt equals equity"), limit: z.number().int().min(1).max(10).default(5) }),
    z.object({ workflow: z.literal("portfolio"), currency, positions: z.array(z.object({ symbol, quantity: z.number().finite().positive().max(1e9), cost_basis: z.number().finite().nonnegative().optional(), purchase_date: z.string().date().optional() }).refine((position) => (position.cost_basis !== undefined) === Boolean(position.purchase_date), "Provide both per-share cost basis and purchase date, or neither")).min(1).max(10).refine((positions) => new Set(positions.map((position) => position.symbol)).size === positions.length, "Use distinct symbols") }),
    z.object({ workflow: z.literal("morning"), date: z.string().date(), timezone: z.string().min(1).max(80).default("Europe/London"), watchlist: z.array(symbol).max(5).default([]) }),
]);

export const number = (value) => typeof value === "number" && Number.isFinite(value) ? value : null;
export const ratio = (a, b) => number(a) !== null && number(b) !== null && b !== 0 ? a / b : null;
export const growth = (current, previous) => number(previous) !== null && previous > 0 && number(current) !== null ? (current / previous - 1) * 100 : null;
const yahooLink = (ticker) => `https://finance.yahoo.com/quote/${encodeURIComponent(ticker)}/`;

export function tableRecords(table) {
    if (!Array.isArray(table?.columns) || !Array.isArray(table?.rows) || !Array.isArray(table?.index)) return [];
    return table.rows.map((row, i) => ({ index: table.index[i], ...Object.fromEntries(table.columns.map((column, j) => [Array.isArray(column) ? column.join("|") : column, row[j] ?? null])) }));
}

export function quarterlySeries(table, cashflow = null) {
    if (!Array.isArray(table?.columns)) return [];
    const metric = (data, names, period) => {
        const row = names.map((name) => data?.index?.indexOf(name)).find((index) => index >= 0);
        const column = data?.columns?.indexOf(period);
        return row !== undefined && column >= 0 ? number(data.rows[row]?.[column]) : null;
    };
    return [...table.columns].filter((period) => typeof period === "string" && /^\d{4}-\d{2}-\d{2}/.test(period))
        .sort().slice(-5).map((period) => {
            const revenue = metric(table, ["TotalRevenue"], period);
            const operating = metric(table, ["OperatingIncome"], period);
            const income = metric(table, ["NetIncome", "NetIncomeCommonStockholders"], period);
            const free = metric(cashflow, ["FreeCashFlow"], period);
            const operatingCash = metric(cashflow, ["OperatingCashFlow", "TotalCashFromOperatingActivities"], period);
            const capex = metric(cashflow, ["CapitalExpenditure"], period);
            return { period: period.slice(0, 10), revenue, operating_income: operating, net_income: income,
                operating_margin: ratio(operating, revenue) === null ? null : operating / revenue * 100,
                net_margin: ratio(income, revenue) === null ? null : income / revenue * 100,
                operating_cashflow: operatingCash,
                free_cashflow: free ?? (operatingCash !== null && capex !== null && capex <= 0 ? operatingCash + capex : null) };
        });
}

function priceRows(response) {
    const data = response?.data;
    return tableRecords(data?.prices).map((row) => ({ date: String(row.index).slice(0, 10), close: number(row.Close) }))
        .filter((row) => row.close !== null && row.close > 0).sort((a, b) => a.date.localeCompare(b.date));
}

export function alignedPerformance(histories) {
    const available = histories.filter((item) => item.rows.length);
    if (available.length !== histories.length || available.length < 2) return { dates: [], series: [] };
    const common = available[0].rows.map(({ date }) => date).filter((date) => available.every(({ rows }) => rows.some((row) => row.date === date)));
    if (common.length < 2) return { dates: [], series: [] };
    return { dates: common, series: available.map(({ symbol, rows }) => {
        const byDate = new Map(rows.map((row) => [row.date, row.close]));
        const base = byDate.get(common[0]);
        return { symbol, values: common.map((date) => (byDate.get(date) / base - 1) * 100), return_pct: (byDate.get(common.at(-1)) / base - 1) * 100 };
    }) };
}

function holdings(table) {
    return tableRecords(table).map((row) => ({ symbol: String(row.index), name: row.Name || String(row.index), weight: number(row["Holding Percent"] ?? row.HoldingPercent ?? row.holdingPercent) }))
        .filter((row) => row.weight !== null && row.weight >= 0 && row.weight <= 1);
}

function newsItems(data) {
    return (Array.isArray(data) ? data : []).slice(0, 5).map((item) => {
        const content = item.content || item;
        return { title: content.title || "Untitled", url: content.canonicalUrl?.url || content.clickThroughUrl?.url || item.link || null,
            published_at: content.pubDate || (item.providerPublishTime ? new Date(item.providerPublishTime * 1000).toISOString() : null), provider: content.provider?.displayName || item.publisher || null };
    });
}

export function createWorkspace(finance) {
    async function run(input) {
        const request = workspaceRequest.parse(input);
        const warnings = [], sources = [], cache = new Map();
        const generated = new Date().toISOString();
        async function fetchData(name, args, section) {
            const key = JSON.stringify([name, args]);
            if (!cache.has(key)) cache.set(key, (async () => {
                try {
                    const value = await finance.call(name, args);
                    sources.push({ section, tool: name, arguments: args, source: value.source || "Yahoo Finance via yfinance", retrieved_at: value.retrieved_at || generated, truncated: value.truncated || false, data: value.data ?? value });
                    if (value.truncated) warnings.push({ section, message: "Provider output was truncated." });
                    return value;
                } catch (error) { warnings.push({ section, message: error.message }); return null; }
            })());
            return cache.get(key);
        }
        const dataset = async (ticker, name, frequency = "yearly") => {
            const response = await fetchData("ticker_data", { symbol: ticker, dataset: name, frequency, limit: 150 }, `${ticker} ${name}`);
            return response?.data ?? null;
        };
        const quote = (ticker) => fetchData("stock_quote", { symbol: ticker }, `${ticker} quote`);
        function profile(ticker, info, price) {
            return { symbol: ticker, name: info?.shortName || info?.longName || ticker, sector: info?.sector || null,
                industry: info?.industry || null, description: info?.longBusinessSummary || null, website: info?.website || null,
                currency: price?.currency || info?.currency || null, financial_currency: info?.financialCurrency || null,
                price: price?.price ?? null, price_date: price?.date || null, source_url: yahooLink(ticker),
                market_cap: number(info?.marketCap), trailing_pe: number(info?.trailingPE), forward_pe: number(info?.forwardPE),
                price_to_book: number(info?.priceToBook), enterprise_to_revenue: number(info?.enterpriseToRevenue),
                total_cash: number(info?.totalCash), total_debt: number(info?.totalDebt) };
        }
        let data;
        if (request.workflow === "research" || request.workflow === "earnings") {
            const ticker = request.symbol;
            const [info, income, cashflow, price] = await Promise.all([dataset(ticker, "info"), dataset(ticker, "income_stmt", "quarterly"), dataset(ticker, "cash_flow", "quarterly"), quote(ticker)]);
            const quarters = quarterlySeries(income, cashflow);
            const latest = quarters.at(-1), previous = quarters.at(-2);
            const changes = { revenue_qoq_pct: growth(latest?.revenue, previous?.revenue), operating_income_change: latest?.operating_income !== null && previous?.operating_income !== null && latest && previous ? latest.operating_income - previous.operating_income : null,
                free_cashflow_change: latest?.free_cashflow !== null && previous?.free_cashflow !== null && latest && previous ? latest.free_cashflow - previous.free_cashflow : null,
                latest_period: latest?.period || null, previous_period: previous?.period || null };
            const observations = [];
            if (changes.revenue_qoq_pct !== null) observations.push(`Revenue ${changes.revenue_qoq_pct >= 0 ? "increased" : "decreased"} ${Math.abs(changes.revenue_qoq_pct).toFixed(1)}% versus the preceding reported quarter.`);
            if (latest?.operating_margin !== null && latest) observations.push(`Operating margin was ${latest.operating_margin.toFixed(1)}% for the quarter ending ${latest.period}.`);
            if (!quarters.length) warnings.push({ section: "Quarterly statements", message: "No usable quarterly statement periods were returned." });
            data = { profile: profile(ticker, info, price), quarters: quarters.slice(-4), changes, observations, basis: "Reported quarterly statements; raw monetary values in the stated financial reporting currency." };
            if (request.workflow === "research") {
                const [targets, calendar, news] = await Promise.all([dataset(ticker, "analyst_price_targets"), dataset(ticker, "calendar"), dataset(ticker, "news")]);
                data.analyst_targets = targets;
                data.calendar = calendar;
                data.news = newsItems(news);
            }
        } else if (request.workflow === "comparison") {
            const companies = await Promise.all(request.symbols.map(async (ticker) => {
                const [info, income, price, history] = await Promise.all([dataset(ticker, "info"), dataset(ticker, "income_stmt", "quarterly"), quote(ticker), fetchData("price_history", { symbol: ticker, period: request.period, adjusted: true, actions: false, limit: 500 }, `${ticker} adjusted prices`)]);
                return { ...profile(ticker, info, price), quarters: quarterlySeries(income), history: priceRows(history) };
            }));
            const periods = companies[0].quarters.map(({ period }) => period).filter((period) => companies.every((company) => company.quarters.some((quarter) => quarter.period === period))).sort();
            const commonPeriod = periods.at(-1) || null;
            const performance = alignedPerformance(companies.map(({ symbol, history }) => ({ symbol, rows: history })));
            if (!commonPeriod) warnings.push({ section: "Financial comparison", message: "No identical fiscal quarter end across all companies; quarterly metrics are not compared." });
            if (!performance.dates.length) warnings.push({ section: "Price comparison", message: "Not enough common observations to calculate aligned returns." });
            data = { companies: companies.map(({ history, quarters, ...company }) => ({ ...company, quarter: quarters.find(({ period }) => period === commonPeriod) || null })), performance, common_period: commonPeriod,
                basis: "Adjusted daily prices aligned to identical observation dates. Valuation metrics are provider snapshots; revenue remains in each company's reporting currency." };
        } else if (request.workflow === "overlap") {
            const funds = await Promise.all(request.symbols.map(async (ticker) => {
                const result = await fetchData("fund_data", { symbol: ticker, dataset: "top_holdings", limit: 100 }, `${ticker} available holdings`);
                return { symbol: ticker, holdings: holdings(result?.data), source_url: yahooLink(ticker) };
            }));
            const shared = funds[0].holdings.map((holding) => {
                const other = funds[1].holdings.find((item) => item.symbol === holding.symbol);
                return other ? { symbol: holding.symbol, name: holding.name, weight_a: holding.weight, weight_b: other.weight, shared_weight: Math.min(holding.weight, other.weight) } : null;
            }).filter(Boolean).sort((a, b) => b.shared_weight - a.shared_weight);
            const complete = funds.every((fund) => fund.holdings.length);
            data = { funds, shared, overlap_pct: complete ? shared.reduce((total, item) => total + item.shared_weight, 0) * 100 : null,
                coverage: funds.map(({ symbol, holdings }) => ({ symbol, count: holdings.length, weight_pct: holdings.length ? holdings.reduce((sum, item) => sum + item.weight, 0) * 100 : null })),
                basis: "Observed overlap = sum of minimum shared weights in the available holdings. Yahoo usually returns top holdings, so this is a lower bound, not complete portfolio overlap. Holdings may have different observation dates." };
        } else if (request.workflow === "screener") {
            const query = { operator: "and", operands: [
                { operator: "eq", operands: ["sector", request.sector] },
                { operator: "gt", operands: ["netincomeis.lasttwelvemonths", 0] },
                { operator: "gt", operands: ["peratio.lasttwelvemonths", 0] },
                { operator: "lt", operands: ["peratio.lasttwelvemonths", request.max_pe] },
                { operator: "lte", operands: ["totaldebtequity.lasttwelvemonths", request.max_debt_equity] },
            ] };
            const result = await fetchData("screen_instruments", { asset: "equity", query, limit: request.limit }, "Equity screening");
            const matches = Array.isArray(result?.data?.quotes) ? result.data.quotes : [];
            data = { filters: query, criteria: { sector: request.sector, positive_net_income: true, max_pe: request.max_pe, max_debt_equity: request.max_debt_equity },
                matches: matches.map((item) => ({ symbol: item.symbol, name: item.shortName || item.longName || item.symbol, price: number(item.regularMarketPrice), currency: item.currency || null, market_cap: number(item.marketCap), trailing_pe: number(item.trailingPE), source_url: yahooLink(item.symbol),
                    explanation: `Returned by Yahoo's ${request.sector} screen with positive trailing net income, positive P/E below ${request.max_pe}, and debt/equity at most ${request.max_debt_equity}%.` })),
                basis: "Provider-screened results are research candidates; missing individual metrics are not invented. The exact executed filters are available below." };
        } else if (request.workflow === "portfolio") {
            if (!Intl.supportedValuesOf("currency").includes(request.currency)) throw new Error("Unsupported display currency.");
            const positions = await Promise.all(request.positions.map(async (position) => {
                const price = await quote(position.symbol);
                const native = price?.currency === "GBp" || price?.currency === "GBX" ? "GBP" : price?.currency;
                const currentPrice = price?.price == null ? null : (price.currency === "GBp" || price.currency === "GBX" ? price.price / 100 : price.price);
                const fx = currentPrice === null || !native ? null : native === request.currency ? { rate: 1, date: price.date } : await fetchData("exchange_rate", { from_currency: native, to_currency: request.currency }, `${position.symbol} FX`);
                const nativeValue = currentPrice === null ? null : currentPrice * position.quantity;
                const displayValue = nativeValue !== null && fx ? nativeValue * fx.rate : null;
                let attribution = null;
                if (position.cost_basis !== undefined && nativeValue !== null && fx) {
                    const cost = (price.currency === "GBp" || price.currency === "GBX" ? position.cost_basis / 100 : position.cost_basis) * position.quantity;
                    const baseFx = native === request.currency ? 1 : null;
                    // Historical FX is fetched using the existing price_history MCP tool.
                    const start = new Date(`${position.purchase_date}T00:00:00Z`); start.setUTCDate(start.getUTCDate() - 7);
                    const end = new Date(`${position.purchase_date}T00:00:00Z`); end.setUTCDate(end.getUTCDate() + 1);
                    const historical = baseFx === null ? await fetchData("price_history", { symbol: `${native}${request.currency}=X`, start: start.toISOString().slice(0, 10), end: end.toISOString().slice(0, 10), adjusted: false, actions: false, limit: 20 }, `${position.symbol} purchase-date FX`) : null;
                    const row = priceRows(historical).filter(({ date }) => date <= position.purchase_date).at(-1);
                    const rate = baseFx ?? row?.close ?? null;
                    if (rate !== null) attribution = { cost_display: cost * rate, stock_effect: (nativeValue - cost) * rate, fx_effect: nativeValue * (fx.rate - rate), total_change: displayValue - cost * rate, purchase_fx_date: row?.date || position.purchase_date };
                }
                return { ...position, price: price?.price ?? null, native_currency: price?.currency || null, quote_date: price?.date || null, fx_rate: fx?.rate ?? null, fx_date: fx?.date || null, native_value: nativeValue, native_value_currency: native, display_value: displayValue, attribution, source_url: yahooLink(position.symbol) };
            }));
            data = { currency: request.currency, positions, complete: positions.every((position) => position.display_value !== null), total: positions.every((position) => position.display_value !== null) ? positions.reduce((sum, position) => sum + position.display_value, 0) : null,
                available_subtotal: positions.reduce((sum, position) => sum + (position.display_value ?? 0), 0),
                basis: "Quantities are user-entered; values use latest available daily quotes and FX observations, excluding fees. Cost basis is per share in the quote's native units. Attribution splits stock-price change at purchase FX from currency change on current native value; excludes dividends and requires split-adjusted cost basis." };
        } else if (request.workflow === "morning") {
            try { new Intl.DateTimeFormat("en-GB", { timeZone: request.timezone }).format(); }
            catch { throw new Error("Invalid timezone."); }
            const benchmarks = await Promise.all(["^GSPC", "^IXIC", "^DJI"].map(async (ticker) => ({ symbol: ticker, quote: await quote(ticker), source_url: yahooLink(ticker) })));
            const end = new Date(`${request.date}T00:00:00Z`); end.setUTCDate(end.getUTCDate() + 1);
            const [earnings, economic, news] = await Promise.all([
                fetchData("calendar_events", { dataset: "earnings", start: request.date, end: end.toISOString().slice(0, 10), limit: 25 }, "Earnings calendar"),
                fetchData("calendar_events", { dataset: "economic_events", start: request.date, end: end.toISOString().slice(0, 10), limit: 25 }, "Economic calendar"),
                fetchData("search_finance", { query: request.watchlist.length ? request.watchlist.join(" ") : "US stock market", dataset: "news", limit: 5 }, "Finance headlines"),
            ]);
            const watchlist = await Promise.all(request.watchlist.map(async (ticker) => ({ symbol: ticker, quote: await quote(ticker), source_url: yahooLink(ticker) })));
            data = { date: request.date, timezone: request.timezone, benchmarks, watchlist, earnings: earnings?.data || null, economic: economic?.data || null, news: newsItems(news?.data),
                basis: "On-demand US market brief. Quotes are latest available daily observations; calendars use the selected date and provider timestamps. The timezone labels your briefing date, not a conversion of unknown provider times." };
        }
        return { workflow: request.workflow, generated_at: generated, source: "Yahoo Finance via yfinance MCP", data, warnings, sources };
    }
    return { run };
}
