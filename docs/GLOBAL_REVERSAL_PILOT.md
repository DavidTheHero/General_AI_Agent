# Broader products: global weekly reversal result

Completed **16 October 2026**, experiment `27fec7fe02854fe68c50fefb8a251aa8`. **No edge established; do not advance this primary to operational promotion.** The recorded cross-scenario assessment is `inconclusive`: base-cost uncertainty spans zero, while the 20-bps scenario rejects positive excess against both declared references. The primary underperforms both references even at 5 bps.

The user removed the product-universe restriction. [Product selection review](PRODUCT_SELECTION.md) considered individual stocks, futures, FX and crypto alongside ETFs. This study uses nine USD, US-session wrappers for global equity styles/regions, Treasury durations, gold and commodity futures. Instrument choice follows economic coverage and currently verifiable accounting, rather than a backtest ranking. Futures, FX and crypto remain eligible for future work once their distinct data and ledgers exist.

## Declaration and data

The [unaltered declaration](GLOBAL_REVERSAL_PROTOCOL.md) fixes the universe, rules, four configurations, costs and inference before acquisition. Original declaration bytes, checksum and source are preserved with the experiment. The alternative four-fund sleeve proposal in the selection review was not run or substituted after these results.

- Universe/order: **SPY, IWM, QQQ, EFA, EEM, IEF, TLT, GLD, DBC**. This adds six instruments beyond the previous studies, bringing the number of distinct tested ETFs to 18.
- Exact acquisition: **2007-01-03 through 2022-12-30**, **4,028 daily observations per instrument**. No missing, duplicate or unexpected requested sessions; no symbol, date or interval substitution. Actions, adjustment flags, structured metadata, retrieval times and original adapter frames are archived and checksummed.
- Initial development: 2008–2012. Continuous validation: 2013–2022, 2,518 sessions. Five two-year folds retain the same holdings and capital across boundaries; no independent fold capital resets.
- Reserved 2023–2025 historical price paths remain unrequested and unevaluated. Retrieval-time metadata and historical researcher/LLM knowledge are not absent; neither is used as a signal feature.
- All portfolios start with USD 100,000, zero-yield cash and no borrowing. Targets execute at the next official open after a completed weekly close. No terminal liquidation is invented.

The primary ranks five-session log returns divided by lagged volatility: 63 sample daily log returns ending at **t−5**, excluding the five-session signal interval. It equally weights the lowest three standardized scores. Signal dates are final official XNYS sessions of ISO weeks, including holiday weeks. Fixed primary **L5/K3** is never replaced by a sensitivity winner. Other declared configurations are L1/K1, L1/K3 and L5/K1.

## Net results and costs

Validation CAGR after declared per-side costs on traded notional:

| Cost | Primary | Weekly equal weight | Prior-training allocation | Excess vs equal weight | Excess vs prior allocation |
|---:|---:|---:|---:|---:|---:|
| 5 bps | 4.58% | 5.46% | 4.83% | −0.87 pp/year | −0.25 pp/year |
| 10 bps | 1.05% | 5.42% | 4.79% | −4.37 pp/year | −3.74 pp/year |
| 20 bps | −5.67% | 5.34% | 4.71% | −11.00 pp/year | −10.37 pp/year |

At 5 bps, the primary turns USD 100,000 into **USD 156,451.47**, compared with USD 170,016.63 equal weight and USD 160,233.83 prior allocation. Positive standalone profit does not establish incremental value. Modeled primary trading costs total **USD 41,220.45**, rising to USD 68,412.06 at 10 bps and USD 97,239.83 at 20 bps. These cumulative dollar costs occur on different compounded capital paths and should not be subtracted again from terminal equity or added mechanically to CAGR.

| Metric, 5 bps | Primary | Equal weight | Prior allocation |
|---|---:|---:|---:|
| Maximum drawdown | 27.49% | 21.82% | 20.38% |
| Annualized daily volatility | 14.70% | 10.97% | 9.81% |
| Daily Sharpe, zero risk-free rate | 0.379 | 0.539 | 0.530 |
| Average gross exposure | 99.88% | 99.88% | 99.88% |
| Cumulative turnover, traded notional / daily opening equity | 686.84 | 7.63 | 7.90 |
| Modeled trading costs | USD 41,220.45 | USD 506.04 | USD 504.61 |

The primary adds turnover, volatility and drawdown without improving base-cost return. Its drawdown reaches 53.83% at 20 bps. Costs are declared sensitivity assumptions, not measurements of historical spreads or auctions. We did not add an unplanned zero-cost run to rescue the result.

SPY passive is context only: 12.19% CAGR at 5 bps, with 33.72% drawdown. It uses this study's first weekly entry opportunity, unlike the earlier monthly studies; those benchmark figures should not be interchanged. A mixed-asset strategy is not required to beat SPY CAGR as its sole alpha hurdle.

![Continuous validation wealth and drawdowns](../artifacts/trading/runtime/27fec7fe02854fe68c50fefb8a251aa8/output/performance.png)

## Expanding references, folds and sensitivity

Before each validation fold, the reference freezes mean **primary target weights** from expanding prior development history only. The five prior windows end in 2012, 2014, 2016, 2018 and 2020. Only this reference adapts; the primary's signal/parameters remain fixed. New reference weights activate by the next eligible execution date, and earlier targets cannot use a future fold's weights. This is a causal allocation control, not exact realized-exposure matching or rolling parameter optimization.

Primary base-cost two-year total returns are **−3.19%, −3.64%, +18.35%, +45.95%, −2.90%**. The fold ledger compounds one continuous capital path: 100,000→96,805.94→93,277.75→110,396.76→161,122.44→156,451.47. Full asset weights, observed concentration, costs and turnover are recorded per fold. The one-third position limit applies to proposed targets; marked weights can drift between rebalances, reaching approximately 36.36% in this sample.

| Configuration, 5 bps | CAGR | Maximum drawdown | Role |
|---|---:|---:|---|
| L1/K1 | 6.68% | 44.76% | Sensitivity |
| L1/K3 | 6.28% | 29.93% | Sensitivity |
| L5/K1 | −0.70% | 41.84% | Sensitivity |
| L5/K3 | 4.58% | 27.49% | Declared primary |

Every base-cost sensitivity comparison remains statistically inconclusive under the declared method. A larger sensitivity CAGR is not a reason to rename that configuration the primary or consume the reserved period.

At 5 bps, paired annualized mean monthly **log-return excess** intervals in decimal units are:

| Reference | Estimate | Lower endpoint | Upper endpoint |
|---|---:|---:|---:|
| Equal weight | −0.008315041 | −0.060836617 | +0.042288316 |
| Prior allocation | −0.002388831 | −0.057953153 | +0.047931696 |

The paired moving-block bootstrap uses 120 months, 12-month blocks, 5,000 draws, seed 20261015 and at least 14 known configurations: 6 first-pilot, 4 sector and 4 new. Intervals are not CAGR differences, factor alpha or calibrated probabilities of an edge. Costs/references/folds share the same path. Limited regimes, block-stationarity and tail assumptions, retrospective universe/design choices and unknown external searches remain limitations. The 20-bps primary intervals lie below zero against both references; the aggregate label remains inconclusive because base-cost intervals include zero. Economically, this primary fails the net-return/cost screen and is not advanced.

## Verification and remaining limits

The real MCP start returned immediately; its initiating connection closed while the runtime worker continued. A fresh client observed running progress and completion. **31 attempts** were recorded before execution and completed: 6 initial-development references/configurations, 4 additional expanding-primary reference windows, and 21 continuous validation portfolios across costs. All 31 reconciled independently against source prices; all attempts, journal events and source/declaration hashes remain inspectable. Software replay is verification, not independent market evidence.

The shared accounting gained an explicit weekly schedule and typed, host-validated targets. Existing monthly behavior remains exactly unchanged on an actual prior sector replay: 2,518 rows, 120 decisions and 426 fills matched in full. **153 Python, 90 backend and 33 React tests**, production build and whitespace checks passed.

These are batch research jobs holding fractional normalized adjusted units, not raw-share positions or a restartable live weekly trading service. The provider's revised adjustment/reinvestment convention, payment-date cash, settlement, taxes, historical spreads/impact, independent-source truth and genuinely forward observations remain unresolved. International ETF closes can be asynchronous with underlying markets; DBC embeds commodity-futures rolls/collateral. EEM's recorded 2008 split and all returned distributions are preserved rather than repaired. Restarted jobs remain explicitly interrupted instead of silently replaying a portfolio.

- [Original MCP request](../artifacts/trading/global-weekly-reversal-20261016/request.json), [start receipt](../artifacts/trading/global-weekly-reversal-20261016/start-receipt.json), [running reconnect](../artifacts/trading/global-weekly-reversal-20261016/reconnected-receipt.json), [completed receipt](../artifacts/trading/global-weekly-reversal-20261016/completed-receipt.json).
- [Full results and attempt references](../artifacts/trading/runtime/27fec7fe02854fe68c50fefb8a251aa8/output/daily-study.json), [generated report](../artifacts/trading/runtime/27fec7fe02854fe68c50fefb8a251aa8/output/report.md), [dataset manifest](../artifacts/trading/runtime/research/daily-studies/27fec7fe02854fe68c50fefb8a251aa8/dataset/manifest.json).
- [Captured declaration](../artifacts/trading/runtime/research/daily-studies/27fec7fe02854fe68c50fefb8a251aa8/declared-protocol.md), [source bundle](../artifacts/trading/runtime/research/daily-studies/27fec7fe02854fe68c50fefb8a251aa8/source), [attempt journal](../artifacts/trading/runtime/research/daily-studies/27fec7fe02854fe68c50fefb8a251aa8/attempts.jsonl).
- [Independent data/signal review](../artifacts/trading/global-weekly-reversal-20261016/data-verification.json), [ledger/reference/replay verification](../artifacts/trading/global-weekly-reversal-20261016/replay-verification.json), [monthly regression](../artifacts/trading/global-weekly-reversal-20261016/monthly-regression.json), [runtime/API verification](../artifacts/trading/global-weekly-reversal-20261016/runtime-verification.json).
- [Local dashboard](http://127.0.0.1:2611/?trading_job=27fec7fe02854fe68c50fefb8a251aa8), [example frozen submission](../examples/weekly_reversal_research.json).

Dataset: `8388eb3cc328b1013aa0d6b0eaf9540fd6b7efb703d50431e13af3404791a11c`.
Protocol: `ae1e9bbb1a3d8a3f0c1d02f2970ff40ed494f665c54701c8affc736583a171f7`.
These are ignored local artifacts. Exact reproduction requires the archived snapshot and source/dependencies; downloading again creates a new provider revision. The wider product universe remains available for distinct, declared economic hypotheses. This result does not support production deployment, a profitable-strategy claim, or opening the reserved prices to search for a more favorable narrative.
