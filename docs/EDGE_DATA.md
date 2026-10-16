# Data for finding and validating a trading edge

Provider documentation verified **15 October 2026** against the primary sources linked below. No accounts were created, credentials obtained, subscriptions activated or data purchased during this review. Documentation describes advertised access; a saved acquisition and its quality report establish what was actually available. Dates, symbols, intervals and providers must never change silently after a failed request.

Scope update, **16 October 2026**: the user removed the product-universe restriction. [Current product review](PRODUCT_SELECTION.md) assesses futures, FX, crypto and individual stocks as well as global/multi-asset ETFs. Free data first and simulated execution remain; different instruments require their actual calendar, currency, funding, roll and accounting models. Completed evidence now includes the [first daily pilot](EDGE_PILOT.md), [sector pilot](SECTOR_EDGE_PILOT.md) and [global weekly reversal pilot](GLOBAL_REVERSAL_PILOT.md). None establishes a profitable edge.

## Research objective

Find a repeatable source of simulated net profit, explain why it might persist, and test whether it survives an untouched period, realistic costs and forward paper observation. MCP makes the resulting research and simulated strategy accessible; exposing a tool does not establish an edge.

Report three different outcomes separately:

- **Market exposure:** a long equity strategy can make money because equities rose. Compare with buy-and-hold under the same capital and cost assumptions.
- **Excess performance:** returns above the declared benchmark are promising evidence, but require exposure, volatility, selection and dependence analysis before being called alpha.
- **Risk reduction:** lower drawdown or volatility can be useful even with lower returns. Compare risk-adjusted results and time invested; do not rename a reduction in equity exposure an excess-return discovery.

Positive historical returns alone satisfy none of the requirements for a supported persistent edge. A failed hypothesis is a useful recorded result. Do not keep trying configurations until a backtest turns green.

## First acquisition: real daily history without a key

Use the installed yfinance adapter for a bounded daily-history probe before buying data. Begin with a small, predeclared list of liquid US-listed ETFs and long-only, unlevered daily or multi-day trend/momentum and reversal hypotheses. ETF selection still carries selection bias; record the entire proposed list, inception dates, exclusions and reasons. A failed symbol must remain in the acquisition report. Do not replace it with a convenient survivor or invent pre-inception returns.

Request explicit start/end dates, `interval=1d`, `auto_adjust=False`, `actions=True`, `repair=False` and `keepna=True`. Preserve all returned OHLCV, adjusted close, dividends, splits and capital-gain fields before normalization, plus timezone/currency metadata and retrieval time. Respect the adapter's exclusive provider end date and record its relationship to the public inclusive end date. A partial current day must not enter completed-day signals. Provider failures and unavailable history must remain explicit.

Yahoo explains that adjusted close incorporates split and dividend adjustments. Use it as an exploratory **total-return proxy**, disclose reinvestment conventions, and reconcile sampled returns against the action records. Historical adjusted levels can change after later actions. An adjusted open derived using the close adjustment factor is a modeling convention, not a price at which actual shares traded. [Yahoo adjustment methodology](https://in.help.yahoo.com/kb/adjusted-close-sln28256.html)

A research calculation using fractional units of an adjusted total-return index can screen a hypothesis. It does not verify whole-share fills, dividend receivables, payment timing, taxes, rounding or available cash. Do not pass these synthetic index units to the existing whole-share portfolio and label them operational positions. Carry both the proxy result and its limitation into every downstream MCP result and report.

yfinance is an independent library rather than a licensed Yahoo trading feed. Its maintainers direct users to Yahoo's data terms and describe personal research/educational use. The software license does not grant redistribution or commercial market-data rights. Keep this probe local; rights to persistent retention, shared dashboards, hosted MCP access, derived-data distribution and commercial use remain unresolved until the applicable provider/exchange terms are checked. [Maintainer documentation and terms links](https://github.com/ranaroussi/yfinance)

## Next cross-check: credentialed free Alpaca historical SIP

Alpaca's Basic documentation advertises US stock/ETF history from 2016 and a historical request allowance of 200 per minute. An account and API credentials are required; this is not a no-key source. Verify the actual account's entitlement with a small request before scheduling bulk work. No paid plan is required by the documented historical access rule when the request ends at least 15 minutes in the past. [Plan comparison](https://docs.alpaca.markets/us/docs/about-market-data-api)

Free live data covers IEX, a single venue. Historical SIP consolidates US exchanges and can be queried with the required delay. Always pin `feed=sip`; fail explicitly if unavailable. Do not substitute IEX bars or volume for consolidated observations. A delayed historical feed is suitable for historical research and reconciliation, not an assumption of immediate live availability. [Feed and entitlement rules](https://docs.alpaca.markets/us/docs/market-data-faq)

For every request pin the timeframe, adjustment, timezone-bearing dates, sort and `asof` symbol-mapping setting. `asof` maps symbol histories; it does not supply a historical investable universe. Retain raw and adjusted views separately. Exhaust `next_page_token`: result limits apply across symbols, and pages are sorted by symbol before timestamp. Archive the request, response and pagination references without authentication headers. [Historical bars contract](https://docs.alpaca.markets/us/reference/stockbars)

Compare overlapping Yahoo and SIP samples for daily OHLC, dividend treatment, split events and session boundaries. Differences should generate an investigation artifact, not a silent switch to whichever source gives higher strategy returns. Quotes and trades are separate observation types; aggregated bars cannot supply executable spreads or the path within a bar.

## Data and hypotheses to add only when useful

| Data | Hypotheses it can support | Required safeguards |
| --- | --- | --- |
| Daily ETF prices, distributions and trading calendar | Trend persistence, relative momentum, multi-day reversal; cash versus market exposure | Inception and selection disclosure; same data/capital/cost benchmark; action-aware return calculation; next eligible execution after the signal |
| Consolidated minute bars plus quotes/trades | Opening-range continuation, short-horizon reversal, spread-aware execution | Verified timestamps/session rules, corrections, halts, quote conditions and cost model; no inference of intrabar order from OHLC alone |
| Original SEC filings and accession-linked facts | Slowly incorporated fundamental information, profitability/quality, filing-event reactions | Facts available as of the filing; amendments retained separately; entity/security mapping; conservative release lag |
| ALFRED macro vintages and source release calendars | A small preregistered macro risk filter or regime interaction | Historical vintages and revisions; release availability rather than observation period; no opportunistic search across hundreds of series |
| Licensed active/delisted stock history, point-in-time membership and fundamentals | Cross-sectional momentum, value and quality | Historical eligibility, delisting proceeds, corporate-action accounting, identifiers and access rights; current screeners cannot reconstruct a past universe |

SEC submissions and XBRL APIs require no API key. Original filing archives and daily/quarterly indexes are available. Preserve accession, form, filing/acceptance times, reporting period, amendments and original document. SEC acceptance is a conservative availability reference, not proof of the first public earnings announcement. Use documented fair-access limits and identify automation. [SEC APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces), [archives and fair access](https://www.sec.gov/about/developer-resources)

FRED/ALFRED API access uses a registered key. Request explicit vintages or initial releases; current revised macro history leaks information into old decisions. Vintage dates are day-level. Official release dates do not necessarily match FRED/ALFRED availability, so use a conservative next-session lag until exact source release and receipt times are verified. [Real-time periods](https://fred.stlouisfed.org/docs/api/fred/realtime_period.html), [observation versions](https://fred.stlouisfed.org/docs/api/fred/series_observations.html), [release-date warning](https://fred.stlouisfed.org/docs/api/fred/release_dates.html)

Paid stock-universe data is justified when a specific hypothesis requires it, rather than as a prerequisite to the first ETF experiment. Nasdaq Data Link's Sharadar SEP covers active and delisted stocks; SF1 documents filing-date **As Reported** dimensions separately from restated **Most Recent** dimensions. Choose the former for historical decisions with a conservative availability lag. Confirm universe coverage and terminal delisting payments, not merely the existence of a delisted ticker. Obtain the relevant license/entitlement before acquisition. [SEP coverage](https://data.nasdaq.com/databases/SEP/documentation?anchor=sample-data), [SF1 methodology](https://data.nasdaq.com/databases/SF1/documentation?anchor=see-also)

Databento provides market-data schemas and separate point-in-time security-master/corporate-action products. Confirm the actual venue, schema, historical start and entitlement: marketing history maxima are not a dataset guarantee. Event time and capture/receive time have different meanings. [Schemas](https://www.databento.tech/docs/schemas-and-data-formats), [security master](https://databento.com/security-master), [corporate actions](https://databento.com/corporate-actions)

Massive offers stock trades, quotes and aggregate flat files. Flat files are unadjusted; REST historical bars are split-adjusted rather than dividend-adjusted. Daily bulk files are delivered the following day, so they cannot be assumed available at the preceding close. Confirm plan-specific history, corrections and entitlements before use. [Flat files](https://massive.com/docs/flat-files/stocks/overview), [adjustments](https://massive.com/knowledge-base/article/is-massives-stock-data-adjusted-for-splits-or-dividends), [delivery](https://www.massive.com/docs/flat-files/quickstart)

## Minimum acquisition and quality record

These are requirements for the research path, not a claim that every existing adapter supplies them:

| Area | Required record |
| --- | --- |
| Request identity | Provider/endpoint and adapter version; exact symbols/identifiers, dates, interval, session, feed, currency, adjustment/repair settings and `asof`; pagination completion |
| Availability | Observation period and timezone; bar start/end; `event_time`, release time, provider receive/update time and local `retrieved_at` when actually available; known latency or explicit unknown |
| Original observations | Original provider payload where accessible, otherwise clearly labeled adapter-level DataFrame; all columns and metadata before filtering; immutable checksum and acquisition ID |
| Corporate actions | Original and amended action records; declaration, ex, record, effective and payment dates as available; splits, distributions, symbol changes, mergers/delistings; adjustment basis and calculation version |
| Quality | Expected calendar versus observed coverage; pre-inception/unavailable history; invalid values; missing or unexpected bars; duplicate identities; conflicting revisions; halts/no-trade intervals; incomplete sessions; summary and examples of each failure |
| Reproducibility and rights | Immutable normalized dataset ID and checksums; transformation/source hashes; retrieval environment; retained failed requests; applicable retention/use/distribution restrictions or unresolved status |

Do not interpolate missing prices or create zero-volume bars and describe them as observed data. Distinguish market closure, no eligible trades, halt, provider omission and unknown cause. Archive corrected events as a new version; never overwrite the original experiment dataset. Explicit identical duplicates may be idempotent, while conflicting duplicates need investigation. Historical corrected bars are not necessarily the bars a streaming strategy received at the time.

## Existing engine boundary and promotion to a simulated MCP strategy

The inspected `trading_agent/engine.py` is an intraday session engine: it starts policy history per session, executes queued targets on the next bar open and liquidates on the scheduled final observed close. `trading_agent/datasets.py` validates intraday session grids and rejects corporate actions because that research ledger cannot account for them. An overnight ETF momentum hypothesis cannot be tested correctly merely by adding `1d` to that interface.

Daily/multi-day exploration therefore needs a distinct declared research path. Before operational promotion, add and verify overnight holdings, raw-price share accounting, splits/distribution receivables, cash timing, session-to-session policy state, risk controls across overnight gaps and restart reconciliation. Reconcile a total-return proxy against the resulting share ledger on known-action fixtures. Existing intraday correctness tests do not establish these behaviors.

Promotion criteria are concrete:

1. Freeze the economic hypothesis, universe, parameters/search budget, execution timing, benchmark, costs and final test period before observing evaluation results. Record unsuccessful attempts too.
2. Evaluate chronological development folds and parameter neighborhoods; stress costs, delay and missing data. Distinguish benchmark-relative return from market exposure and risk reduction. Reserve the final period and report uncertainty and dependence.
3. Replicate promising findings with an independent data source and ledger. Require future-data perturbation and replay/continuous equality tests for the implemented horizon; verify action, stale-data, cancellation and restart behavior.
4. Collect genuinely forward simulated observations with the frozen version. Historical LLM decisions require contamination and nondeterminism disclosure; explanatory narratives do not replace measured evidence.
5. Expose only a versioned simulated strategy through bounded MCP operations with explicit dataset, experiment and provenance IDs, assumptions, quality failures and the assessment `supports`, `inconclusive` or `rejects`. Host code must own positions, accounting and risk; workers must survive MCP disconnection.

The immediate useful deliverable is a real-data probe plus a fully recorded, falsifiable ETF experiment. No source list, software test count or synthetic profit establishes a profitable edge.
