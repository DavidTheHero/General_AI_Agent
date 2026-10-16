# Next bounded hypothesis: sector ETF momentum

Local research declaration dated **16 October 2026**, prepared before acquiring or evaluating this sector universe. This is a recorded research plan, not an independent preregistration or evidence of an edge. Status update: **completed, inconclusive**. The worker preserved the original declaration bytes before acquisition; [actual results and immutable declaration](SECTOR_EDGE_PILOT.md).

## Rationale and lineage

The first SPY/IEF/GLD pilot found no established edge. Its frozen momentum126 configuration earned more than its equal-weight reference with higher volatility, larger drawdown and broad uncertainty. Retuning that configuration against validation would weaken the evidence. [Actual pilot](EDGE_PILOT.md)

Industry-level momentum offers a separately motivated question: does slow persistence among equity sectors add value beyond passive sector/equity exposure after costs? The primary literature precedes these experiments; it does not establish a current long-only ETF edge. [Moskowitz and Grinblatt, 1999](https://onlinelibrary.wiley.com/doi/abs/10.1111/0022-1082.00146)

## Frozen proposal

| Item | Declaration |
|---|---|
| Universe | XLB, XLE, XLF, XLI, XLK, XLP, XLU, XLV, XLY, with SPY used only as an additional benchmark. |
| Universe caveat | Original sector ETF cohort, chosen retrospectively. Verify inception and session coverage. Do not backfill funds with index returns or silently substitute XLRE/XLC. Sector taxonomy/holdings changes remain part of the observed ETF histories. |
| Observation window | Daily bars/actions from 2000 through 2022. Earlier observations serve warm-up only. Preserve original responses, adjustment settings and metadata. |
| Training / validation | 2001–2012 training; 2013–2022 fixed-parameter validation with chronological subperiod diagnostics. This is not rolling retraining. |
| Reserved prices | Keep 2023–2025 reserved, consistent with the first pilot. No acquisition or evaluation of that price path under this proposal. |
| Signal | At completed month-end `t`, rank each sector by `AdjClose[t-21] / AdjClose[t-L] - 1`, where L is 126 or 252 sessions. Dates refer to session offsets. This excludes the latest 21 sessions; it is not a 252-session window ending 21 sessions ago. |
| Targets | Equal weight the top K sectors, with K in {1,3}. Long-only, gross target <=1, no borrowing. Stable universe order breaks exact ties. No added absolute-momentum, volatility or macro filter. |
| Primary configuration | L=252, K=3. Other three combinations are declared sensitivity configurations. Do not replace the primary with a validation winner. |
| Timing | Observe only completed closes; execute the next session open under a disclosed model. Retain overnight positions. No terminal liquidation invented from unavailable prices. |
| Capital / costs | USD100,000 initial capital, zero-yield cash; 5 bps one way on traded notional, with 10 and20 bps stress. Same conventions for all benchmarks. |
| Benchmarks | Monthly equal-weight sector basket, SPY passive and zero-yield cash. Report equity exposure, volatility, drawdown and turnover alongside return. |
| Search budget | Exactly four sector configurations. Include the six first-pilot configurations in the declared research lineage; repeated software verification runs are not new independent observations. Record all failed/cancelled attempts. |
| Inference | Paired monthly excess to both equity benchmarks; predeclared 12-month blocks and conservative multiplicity treatment across known protocol/configuration searches. Report assumptions and uncertainty rather than equating a positive mean with alpha. |

Data-use rights and source coverage must be checked; a free download is not a redistribution license. See [data-source plan](EDGE_DATA.md).

## Decisions before opening the reserved period

A candidate remains inconclusive if its extra return is cost-sensitive, uncertainty spans zero, results rely on one regime or increased market/concentration risk explains the apparent improvement. Lower drawdown alone answers a risk-control question. Positive standalone P&L answers a profitability question. Neither alone establishes predictive edge.

Any advancement requires independent data replication of the unchanged primary rule, raw-share corporate-action/payment-date accounting with reconciliation, a locked final-test protocol and genuinely forward simulated observations. An adjusted-index screen remains `research_only`; do not publish it as a validated operational strategy MCP. If the fixed proposal fails, record the failure before declaring a genuinely new hypothesis and expanding the search count.

The declaration above was frozen before implementation and acquisition. The completed study retained its primary and four-configuration budget. No reserved historical price path was requested; no strategy was promoted. [Actual results](SECTOR_EDGE_PILOT.md)
