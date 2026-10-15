# yfinance MCP Capabilities

This server wraps the public market-data capabilities of the pinned **yfinance 1.7.0** package. It exposes **18 tools** and the `yfinance://capabilities` resource. Python method/property aliases share operations; it does not expose arbitrary `getattr`, Python code execution, or unrestricted package configuration.

## Tool Inventory

| MCP tool | Package surface | Scope |
| --- | --- | --- |
| `search_stocks` | `Search.quotes` | Existing company/ticker resolution. |
| `stock_quote` | `Ticker.history`, history metadata | Existing latest daily price and change. |
| `stock_history` | `Ticker.history` | Existing last 1–366 daily observations. |
| `exchange_rate` | Currency-pair `Ticker.history` | Existing FX reference rate. |
| `ticker_data` | Ticker properties and getters | Fundamentals, statements, corporate actions, estimates, holders, news, valuation and option expiries. |
| `price_history` | `Ticker.history` | Period/date range, daily/intraday intervals, adjustments, extended hours, corporate actions and repair. |
| `download_prices` | `download`; equivalent to Tickers history/download | Up to ten symbols; preserves table axes and multi-level columns. |
| `search_finance` | `Search` | Quotes, news, lists, navigation, research or combined results. |
| `lookup_instruments` | `Lookup` | Stocks, ETFs, funds, indices, futures, currencies and cryptocurrencies. |
| `market_data` | `Market`, `MarketRegion` | Regional summary/status; unavailable status remains null. |
| `calendar_events` | `Calendars` | Earnings, economic events, IPOs and splits with pagination. |
| `fund_data` | `FundsData` | Fund descriptions, operations, allocation, holdings, ratings and sectors. |
| `sector_data` | `Sector` | Overview, industries, leading companies, ETFs, funds and reports. |
| `industry_data` | `Industry` | Overview, parent sector, leading/growth/performing companies and reports. |
| `option_chain` | `Ticker.option_chain` | Calls, puts and underlying data for an optional expiry. |
| `screener_catalog` | Query classes, predefined screeners | Valid field/value discovery for equity, fund and ETF filters. |
| `screen_instruments` | `screen`, EquityQuery/FundQuery/ETFQuery | Named screeners or validated recursive JSON filters. |
| `stream_prices` | `AsyncWebSocket`; equivalent live data to WebSocket/Ticker.live/Tickers.live | Finite message collection; connection closes afterward. |

## Ticker Datasets

`ticker_data` accepts a fixed schema enum, not an arbitrary attribute name:

- Identity and prices: `info`, `fast_info`, `isin`, `history_metadata`.
- Corporate actions/shares: `actions`, `dividends`, `splits`, `capital_gains`, `shares`, `shares_full`.
- News/events: `news`, `calendar`, `earnings_dates`, `sec_filings`.
- Statements: `income_stmt`, `balance_sheet`, `cash_flow`, legacy `earnings`.
- Analyst data: `recommendations`, `recommendations_summary`, `upgrades_downgrades`, `analyst_price_targets`.
- Estimates: `earnings_estimate`, `revenue_estimate`, `earnings_history`, `eps_trend`, `eps_revisions`, `growth_estimates`.
- Holdings: `insider_purchases`, `insider_transactions`, `insider_roster_holders`, `major_holders`, `institutional_holders`, `mutualfund_holders`.
- Other: `sustainability`, `valuation`, `options` (available expiry dates).

Property/getter aliases use the same dataset. `financials`/`incomestmt` map to `income_stmt`; `balancesheet` maps to `balance_sheet`; `cashflow` maps to `cash_flow`. Use `frequency` (`yearly`, `quarterly`, `trailing`) for statements. Legacy earnings may be unavailable/deprecated and does not support trailing frequency.

## Examples

Run from the repository root; install the Python finance requirements first.

```bash
npm run mcp:finance -- list
npm run mcp:finance -- ticker_data '{"symbol":"NVDA","dataset":"income_stmt","frequency":"quarterly","limit":20}'
npm run mcp:finance -- ticker_data '{"symbol":"NVDA","dataset":"analyst_price_targets"}'
npm run mcp:finance -- price_history '{"symbol":"NVDA","period":"5d","interval":"15m","limit":50}'
npm run mcp:finance -- download_prices '{"symbols":["NVDA","MSFT"],"period":"1mo","adjusted":true}'
npm run mcp:finance -- fund_data '{"symbol":"SPY","dataset":"top_holdings"}'
npm run mcp:finance -- option_chain '{"symbol":"NVDA","limit":10}'
npm run mcp:finance -- market_data '{"market":"GB","dataset":"summary"}'
npm run mcp:finance -- screener_catalog '{"asset":"equity"}'
npm run mcp:finance -- screen_instruments '{"predefined":"day_gainers","limit":5}'
npm run mcp:finance -- screen_instruments '{"query":{"operator":"gt","operands":["intradaymarketcap",1000000000]},"limit":5}'
npm run mcp:finance -- stream_prices '{"symbols":["NVDA"],"seconds":3,"limit":10}'
```

Custom screeners accept `{operator, operands}`. Logical `and`/`or` operands contain nested queries. Supported fields/values come from the selected asset's `screener_catalog`; invalid fields are rejected by yfinance. Filters allow at most six levels and twenty operands per node.

## Results and Limits

The original four tools keep their existing schemas. New tools return:

```json
{
  "source": "Yahoo Finance via yfinance",
  "retrieved_at": "ISO timestamp",
  "data": {},
  "truncated": false
}
```

Tables have `columns`, `index`, and `rows`, retaining statement periods, metric names, timezone-bearing dates and batch ticker columns. NaN, infinity, pandas NA and NaT become JSON null, never zero. `retrieved_at` is request processing time, not a guarantee of market-data freshness. Dataset observation dates remain in the data.

Output defaults to 100 rows/items, allows up to 500, and limits tables to 100 columns. Truncation is explicit. Results exceeding 256 KB are rejected with an instruction to narrow the request. Screen/search limits are smaller; calendars require a window of at most 31 days. Yahoo's own intraday retention and availability restrictions still apply. No unbounded live subscription is held: streaming lasts at most ten seconds and may return no messages when markets are closed.

Client calls have a 30-second deadline, including a tool's provider work. Multi-symbol downloads can exceed that deadline; narrow the symbol/date selection if necessary. `progress=False` and `verbose=False` protect stdout, which is reserved for MCP.

## Chat Integration

For advanced finance questions, the router selects `finance_data` and a named MCP tool. The agent then discovers that tool's argument schema and makes a second structured model call to produce its arguments. Python validates those arguments before provider access. The response displays bounded JSON data with source, retrieval time and truncation status. Ordinary quotes, comparisons and currency follow-ups keep their existing presentation.

Direct MCP and CLI access can call every tool without Ollama. Model interpretation is a separate layer; successful tool exposure does not guarantee every natural-language phrasing will route correctly.

## Administrative Boundaries

`Auth`, session objects, credential access, logging switches, cache filesystem paths, `set_config`, and arbitrary provider URLs are server administration rather than market-data tools. They are not callable through MCP. Deployers manage these settings in Python/environment configuration. The capability resource records these exclusions explicitly.

This implements the package's data capability families, with bounded equivalents for collection/live APIs; it is not a one-to-one remote mirror of every Python method. New yfinance versions require a fresh API audit before changing the pinned dependency.

Source: [official yfinance API reference](https://ranaroussi.github.io/yfinance/reference/index.html). Yahoo/provider errors and data-use terms still apply; no licensed real-time feed or trading execution is promised.

## Application Workflows

The React **Finance workspace** combines these MCP tools into seven reports: company research, company comparison, earnings exploration, ETF overlap, explained screening, portfolio currency attribution and an on-demand market morning brief. See the [workspace usage guide](../../README.md#finance-workspace). These are application workflows exposed by Express at `/finance/workspace`; the MCP server retains its 18 data tools.

Portfolio attribution uses `stock effect = (current native value − native cost) × purchase FX` and `FX effect = current native value × (current FX − purchase FX)`. Their sum equals total value change in the display currency. Historical FX uses the latest available daily observation on or before purchase; missing FX prevents a complete portfolio total. GBp/GBX quotes are normalized to GBP before conversion.

## Chat Agent Loop

The Node host can call these tools repeatedly within a six-action decision budget. It feeds results and provider errors back to Ollama, discovers input schemas, blocks duplicate execution and records `metadata.agent_trace`. Company briefs use `resolve_company` in the Node host for bounded discovery and metadata checks, then reporting. The resolver is an application tool combining MCP calls, not an additional Python MCP endpoint. An empty name search permits another search or lookup, rather than a guessed ticker. Tool availability and structured output names change with progress; the Python MCP data tools retain their original interfaces.

## Trading simulation integration

A separate trading MCP server now exposes `trading_start`, `trading_status`, `trading_list` and `trading_stop`. It controls the independent Python runtime and integrates with chat and the React Trading desk; these operations are not part of this server's 18 read-only finance tools. See [deployment and operation](../../deploy/README.md).
