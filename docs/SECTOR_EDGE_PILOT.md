# Sector momentum: actual research result

Completed **16 October 2026**, experiment `00de65070c644158be786f542cfc82d6`. **Assessment: inconclusive; research_only.** The unchanged primary rule outperformed both passive references at the base assumed cost, but its excess disappeared under cost stress and the uncertainty intervals include zero. This is a research lead, not an established profitable edge or an operational strategy.

## Frozen question and actual observations

The [local declaration](NEXT_EDGE_PROTOCOL.md) preceded acquisition of this universe. Its original bytes and SHA-256 are preserved in the experiment's [declared-protocol.md](../artifacts/trading/runtime/research/daily-studies/00de65070c644158be786f542cfc82d6/declared-protocol.md) and [preregistered.json](../artifacts/trading/runtime/research/daily-studies/00de65070c644158be786f542cfc82d6/preregistered.json). This is local recording, not independent preregistration.

- Original nine sectors: XLB, XLE, XLF, XLI, XLK, XLP, XLU, XLV and XLY. SPY is a separate reference, never ranked.
- Exact requested development observations: **3 January 2000–30 December 2022**, **5,787 daily bars per instrument**. Calendar checks found zero missing, duplicate or unexpected session rows. The archive preserves each returned adapter frame, actions, structured metadata, retrieval timestamps, settings and checksums; it does not preserve original HTTP wire bytes.
- Training: **2001–2012**; validation: **2013–2022**, 2,518 sessions and 120 monthly observations. These are fixed-parameter chronological periods, not rolling retraining.
- Signal: at a completed month-end, rank `AdjClose[t-21] / AdjClose[t-L] - 1`. L is 126 or 252; K is 1 or 3. No positivity, volatility or trend filter was added. Ties retain declared universe order.
- Primary fixed before acquisition: **L252/K3**. Other combinations are sensitivity only; training and validation winners cannot replace it.
- Initial USD 100,000; long-only, at most 100% gross allocation, no borrowing; zero-yield cash. Targets execute at the next session's adjusted-open proxy. Overnight normalized fractional units carry distributions through the adjusted series, without double-crediting them. These are not raw-share orders.
- References: monthly equal-weight nine sectors and SPY passive. Both share entry opportunities, capital, costs and end valuation. Every attempt starts in cash and first signals at an in-period month-end. No terminal sale was invented.
- **2023–2025 historical price paths were not requested or evaluated.** Metadata includes retrieval-time context, which is not used by signals. Historical researcher/LLM knowledge and incidental search snippets prevent claiming that all contextual knowledge of the reserved period is absent.

## Primary result and cost stress

Net validation CAGR, with per-side costs charged on traded notional:

| Cost | Primary L252/K3 | Equal-weight sectors | SPY passive | Excess versus sectors | Excess versus SPY |
|---:|---:|---:|---:|---:|---:|
| 5 bps | 12.60% | 11.80% | 11.83% | +0.80 pp/year | +0.78 pp/year |
| 10 bps | 12.33% | 11.78% | 11.82% | +0.55 pp/year | +0.51 pp/year |
| 20 bps | 11.78% | 11.74% | 11.81% | +0.05 pp/year | −0.03 pp/year |

At 5 bps the primary ends at **USD 327,365.69**, compared with **USD 304,813.48** for sectors and **USD 305,497.11** for SPY. These are historical total-return proxy profits. The cost scenarios are assumptions, not measured historical execution costs.

| Validation metric, 5 bps | Primary | Equal-weight sectors | SPY passive |
|---|---:|---:|---:|
| Maximum drawdown | 30.27% | 36.66% | 33.72% |
| Annualized daily volatility | 17.78% | 16.96% | 17.36% |
| Mean equity exposure | 99.17% | 99.17% | 99.17% |
| Daily Sharpe, zero risk-free rate | 0.757 | 0.743 | 0.731 |
| Cumulative traded notional / daily opening equity | 48.63 | 3.76 | 1.00 |
| Modeled investor trading costs | USD 4,395.23 | USD 328.39 | USD 49.98 |

The primary's costs rise to **USD 16,833.83** at 20 bps. Its lower maximum drawdown coexists with slightly higher daily volatility. Concentrated sector positions, structural sector changes and equity exposure still require attribution; these figures do not establish factor alpha.

![Primary validation wealth and drawdowns](../artifacts/trading/runtime/00de65070c644158be786f542cfc82d6/output/performance.png)

## Sensitivity, chronology and uncertainty

All four declared configurations are retained below at 5 bps. The strongest sensitivity result is not promoted to primary after seeing validation.

| L / K | Net CAGR | Maximum drawdown | Annualized volatility | Role |
|---|---:|---:|---:|---|
| 126 / 1 | 12.23% | 31.15% | 22.46% | Sensitivity |
| 126 / 3 | 13.22% | 34.04% | 17.90% | Sensitivity |
| 252 / 1 | 16.61% | 31.15% | 22.72% | Sensitivity; concentrated, broad uncertainty |
| 252 / 3 | 12.60% | 30.27% | 17.78% | Declared primary |

The primary trailed SPY in four of the five chronological two-year diagnostics. Its annualized advantage over the full validation period depends on the last two-year segment: 2021–2022 total proxy return was 35.60%, versus 5.33% for SPY. Those subperiod figures diagnose regime dependence; they are not new selection criteria or independent confirmations.

The uncertainty statistic is annualized mean paired monthly **log-return excess**, not CAGR difference. At 5 bps, decimal annual-log units are:

| Reference | Estimate | Lower endpoint | Upper endpoint |
|---|---:|---:|---:|
| Equal-weight sectors | +0.007137783 | −0.048622809 | +0.055958905 |
| SPY passive | +0.006913754 | −0.056010800 | +0.085189617 |

Both intervals include zero. Resampling uses 5,000 paired draws, contiguous 12-month blocks and seed 20261015. Correction includes the six earlier ETF configurations plus these four: per-configuration alpha 0.05/10, quantiles 0.0025 and 0.9975. Costs and benchmarks are dependent views of the same path. Limited regimes, block-stationarity assumptions, tail approximation, retrospective universe choice and unknown external searches prevent calibrated significance or a probability of an edge. All sensitivity comparisons also remain inconclusive under this method.

## Data issue: XLF's in-kind distribution

The issuer's 2016 annual report confirms distribution of **0.139146 XLRE shares per XLF share**, paid 22 September 2016. Yahoo represents the 19 September ex-event as `Stock Splits = 1.231`, with zero dividend/capital-gain entries that day. Its earlier OHLC are already rescaled; the adjusted series is smooth across the event. This is a provider encoding, not actual XLF shares multiplying by 1.231.

No observation was repaired, dropped or replaced. The event's exact archived window remains in `known_action_review`, marked unresolved for operational accounting. Smoothness cannot establish entitlement, cash-in-lieu, payment-date treatment or executable total return. [Primary sources, source archives and detailed review](SECTOR_DATA_NOTES.md)

A partial independent check compared 30 September 2015–30 September 2016: the archived adjusted-close series returns 7.048%, versus issuer-reported NAV 7.36% and market return 7.42%. The issuer uses NAV distribution reinvestment and midpoint market prices; Yahoo's close/proxy convention differs. The unresolved 31–37-bps difference is neither proof of a vendor error nor successful independent replication.

## Reproduction, MCP and acceptance evidence

This was **one** real sector acquisition/study, initiated through `trading_sector_research_start({"research": {}})`. Its initiating MCP client disconnected while the independent runtime worker continued. A fresh client observed progress and completion. The scoped status tool, Express API and Vite proxy return the same exact job ID. [Dashboard receipt](http://127.0.0.1:2611/?trading_job=00de65070c644158be786f542cfc82d6)

The worker recorded **24 attempts**: six training configurations/references plus six validation configurations/references at each of three costs. Each started attempt was journaled before execution; all 24 completed and independently reconciled. Failed/cancelled attempt handling, restart labels and fixed-primary behavior have separate offline tests. Software verification repetitions are not additional market evidence or searched configurations.

An independent offline pass rebuilt all 24 ledgers from the frozen prices: **63,426 daily marks and 9,068 fills** reconciled. A full replay of the primary validation attempt matched exactly. A separate calculation reranked all **2,016 momentum decisions** across the candidate attempts; all matched. Source/declaration hashes and all 48 journal events were checked. These checks establish internal consistency, not provider accuracy or an edge.

- [Completed MCP receipt](../artifacts/trading/sector-edge-pilot-20261016/completed-receipt.json), [initial receipt](../artifacts/trading/sector-edge-pilot-20261016/start-receipt.json), [reconnected running receipt](../artifacts/trading/sector-edge-pilot-20261016/reconnected-receipt.json).
- [Full study, comparisons and attempt references](../artifacts/trading/runtime/00de65070c644158be786f542cfc82d6/output/daily-study.json), [generated report](../artifacts/trading/runtime/00de65070c644158be786f542cfc82d6/output/report.md), [dataset manifest](../artifacts/trading/runtime/research/daily-studies/00de65070c644158be786f542cfc82d6/dataset/manifest.json).
- [Immutable Python source bundle](../artifacts/trading/runtime/research/daily-studies/00de65070c644158be786f542cfc82d6/source), [attempt journal](../artifacts/trading/runtime/research/daily-studies/00de65070c644158be786f542cfc82d6/attempts.jsonl), [independent replay verification](../artifacts/trading/sector-edge-pilot-20261016/replay-verification.json), [independent data/action review](../artifacts/trading/sector-edge-pilot-20261016/verification.json).

Dataset ID: `d65be74bca2e3a0086ae7e22d735331439750aa042fb67cc364d2d3418d8ae10`.
Protocol ID: `4152366d904ad4f7397efa8626a6261b46d0309e61f6f2d4f2b88cda7c08acaf`.
The ignored local artifacts are not automatically included in a fresh checkout. Exact reproduction requires this checksummed snapshot and the recorded source/dependency versions; a new Yahoo request is a new revised snapshot, not an identical replay. [Example frozen request](../examples/sector_edge_research.json)

Validation: **127 Python tests, 86 backend tests, 32 React tests**, production build and diff checks passed. These verify implementation and reproducibility controls; they do not validate a financial edge.

The next useful evidence is independent data/action reconciliation and prospective testing under unchanged rules, rather than switching to the validation winner. The primary's cost/regime sensitivity does not justify opening the reserved period to search for a better result. Raw-share accounting, historical quote/cost evidence, independent-source replication, a locked final-test protocol and genuinely forward simulated observations remain unresolved. Execution remains simulated; no strategy has been promoted as profitable.
