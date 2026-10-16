# Global ETF short-term reversal: local declaration v1

Declared **16 October 2026**, before acquiring the proposed basket or inspecting its strategy returns. This is a local research declaration, not independent preregistration. The user has removed the product-universe restriction; free data first, simulated execution and the existing reserved-price boundary remain in force.

## Economic question and product choice

Temporary selling pressure can create a later recovery as liquidity demand subsides. Published equity research links short-term reversal to liquidity provision and regime-dependent risk; it does not establish a modern, long-only cross-asset ETF edge. Extending that mechanism to this basket is a new inference to falsify. Trading costs are a central potential failure, not a detail to add after a profitable curve. [Nagel, Evaporating Liquidity](https://www.nber.org/papers/w17653), [Frazzini, Israel and Moskowitz, implementation-cost study](https://www.aqr.com/insights/research/working-paper/trading-costs-of-asset-pricing-anomalies)

Product choice follows economic coverage and implementable observations rather than retrospective winners. Use USD, US-session ETFs for US large/small/growth equities, developed/emerging foreign equities, intermediate/long Treasuries, gold and commodity futures exposure. These wrappers permit a common calendar and capital convention while expanding underlying exposures. International ETF prices can reflect stale underlying-market prices and local-market holidays; commodity-fund returns include roll/collateral effects. A fixed surviving universe remains retrospective. [Product/data review](PRODUCT_SELECTION.md)

## Frozen protocol

| Item | Declaration |
|---|---|
| Universe/order | **SPY, IWM, QQQ, EFA, EEM, IEF, TLT, GLD, DBC**. No substitution, index backfill or exclusion after seeing performance. |
| Requested observations | Daily OHLCV, adjusted close and all returned actions from **2007-01-03 through 2022-12-30**. Explicit provider end-exclusive 2022-12-31; auto_adjust/back_adjust/repair/prepost/rounding false; actions/keepna true. |
| Initial development | **2008-01-02 through 2012-12-31**; 2007 serves warm-up. |
| Validation | Continuous **2013-01-02 through 2022-12-30**, with folds 2013–2014, 2015–2016, 2017–2018, 2019–2020, 2021–2022. Capital and holdings carry across validation fold boundaries. |
| Reserved prices | **2023-01-03 through 2025-12-31** remain unrequested and unevaluated. Metadata/public literature can reveal contextual historical information; this boundary does not establish globally unknown history. |
| Signal schedule | Completed final XNYS session of each ISO week, determined solely from the official session calendar. Execute at the next official session open. |
| Signal | For each ETF, score `log(AdjClose[t]/AdjClose[t-L]) / (sqrt(L) * sigma)`; sigma is sample stddev (`ddof=1`) of exactly 63 daily log returns ending at **t-L**. Neither the current L-session return nor later observations enter sigma. |
| Warm-up/failures | Require at least **L+64** completed closes. Missing/invalid observations, nonfinite or zero sigma fail explicitly; do not omit the asset, fill gaps or synthesize returns. |
| Positions | Equal-weight the lowest K scores; ties keep declared universe order. No absolute-return, volatility threshold, trend, VIX or macro filter. Long-only; gross target 1; no borrowing. Targets remain until the next weekly target. |
| Four configurations | L in {1,5}, K in {1,3}. **Primary L5/K3**, fixed before acquisition. No training/validation winner replaces it. |
| Capital/cost | USD 100,000 initially; cash earns 0%; fractional normalized total-return proxy units. Costs 5 bps per side on traded notional; stresses 10 and 20 bps. Fees cannot create borrowing. |
| Main reference | Equal-weight all nine ETFs, rebalanced on the same weekly schedule and capital/cost conventions. |
| Allocation reference | At each validation fold, freeze mean target weights from the primary's expanding **prior development observations only**. Rebalance those fixed weights weekly during that fold. Label training-allocation matched, not exact realized-exposure matched. |
| Context references | SPY passive with the same initial weekly entry opportunity, and zero-yield cash. Do not require a low-equity allocation to beat SPY CAGR as its sole criterion. |
| End valuation | Mark remaining positions; no invented terminal exit. Adjusted units are not raw-share operational fills. |
| Chronology | Initial development plus expanding prior windows for the allocation reference. The primary has fixed parameters; no rolling parameter retraining is claimed. Freeze each reference before its validation fold; later folds cannot change earlier references or targets. |
| Inference | Paired monthly excess on continuous validation path; twelve-month moving blocks, 5000 draws, seed 20261015, correction across at least **14** known configurations (6 initial + 4 sector + 4 new). Report each fold and cost, concentration, asset exposure, volatility, drawdown, turnover and costs. Costs/references/folds are dependent views. |

## Acceptance criteria and promotion boundary

1. Capture this declaration, source, dependencies, request, original adapter responses, metadata, quality/action reports and checksums before evaluation. Record attempted configurations and failures before execution. Do not change requested data after an acquisition failure.
2. Extend the shared accounting only with an explicit weekly schedule. Preserve existing monthly-study behavior. Validate typed strategy proposals in deterministic host code; enforce exact symbols, finite nonnegative weights, position/gross caps and cash-constrained execution.
3. Verify rank/lag/volatility known answers, holiday-week execution, no same-close fills, invalid targets, costs, future-data perturbation, causal expanding reference weights, fold continuity and replay. Independently reconcile every attempted ledger against the archived source prices.
4. Expose a bounded background research job with exact ID, progress, artifacts, comparison evidence and cancellation; disconnecting MCP must not cancel the worker. Keep results `research_only` and interrupted states explicit.
5. Evaluate the unchanged primary against both main and prior-allocation references at every cost. A positive estimate with uncertainty spanning zero, a cost-sensitive result or concentration/regime dependence remains inconclusive. Infer no alpha solely from positive profit or lower drawdown.

Independent-source replication, raw-share corporate-action/payment-date accounting, measured execution costs, a locked final protocol and genuinely forward simulated observations remain prerequisites to operational promotion. No broker orders, subscriptions or provider accounts are authorized by choosing a product universe.

Status at declaration: **not run**. Preserve these bytes before any subsequent outcome note; report results in a separate document.
