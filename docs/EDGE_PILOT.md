# First real-data daily edge pilot

Report dated **16 October 2026**. The protocol and original Yahoo acquisition were recorded on **15 October 2026**. This report describes completed experiment `20261015000000000000000000000002`; it does not reinterpret a later rerun as a new independent experiment.

## Verification follow-up on 16 October

Experiment `20261016000000000000000000000003` reacquired the identical declared development window after correcting metadata capture. Structured USD/session metadata, explicit lazy-field omissions and corporate-action counts are now preserved; original snapshots were not modified. The full Python source was copied and its hashes matched the recorded execution environment. All **32 attempts** reconciled again. This is software/data verification, not an independent market sample.

The fresh provider snapshot differs slightly in adjusted-close values (maximum relative differences approximately 0.00010% for SPY and0.00021% for IEF; GLD unchanged). The selected rules and rounded conclusions below are unchanged. These differences reinforce the need to archive exact revised-data snapshots. [Verified summary](../artifacts/trading/daily-edge-pilot-20261015/verified-output/daily-study.json), [equity/drawdown chart](../artifacts/trading/daily-edge-pilot-20261015/verified-output/performance.png), [generated report](../artifacts/trading/daily-edge-pilot-20261015/verified-output/report.md)

The persistent runtime was refreshed only after confirming it had no active jobs. MCP job `bebba896f44a4a1a9e62c62267fc5667` then used an exact checksummed copy of that development snapshot. The initiating MCP client disconnected; a fresh client inspected completion. Its metrics matched the CLI run exactly, all32 attempts reconciled and final-period prices remained unrequested. This rerun also is not independent strategy evidence. [MCP verification](../artifacts/trading/daily-edge-pilot-20261015/runtime-verification.json), [local dashboard receipt](http://127.0.0.1:2611/?trading_job=bebba896f44a4a1a9e62c62267fc5667)

The next independently motivated sector-momentum question was declared in [NEXT_EDGE_PROTOCOL.md](NEXT_EDGE_PROTOCOL.md), with four configurations. It has since completed; [the separate sector report](SECTOR_EDGE_PILOT.md) records its inconclusive evidence without changing this pilot's selection or conclusions. The original result report continues below.

**No profitable edge has been established.** Both selected strategies made historical proxy profits. The SPY trend strategy underperformed SPY while reducing risk; cross-asset momentum modestly outperformed its diversified benchmark with higher risk and broad uncertainty. The recorded assessment is **inconclusive**, with promotion blocked and the final period unobserved by this protocol.

## Data and frozen protocol

- Universe: SPY, IEF and GLD, a fixed surviving ETF set selected retrospectively.
- Acquired observations: **3 January 2005–30 December 2022**, **4,531 daily bars per ETF**. The quality report found zero missing, duplicate or unexpected session rows. These checks establish coverage against the configured calendar, not independent accuracy.
- Training: **3 January 2006–31 December 2012**, 1,761 trading sessions. The stored training end is `2013-01-01`, a market holiday.
- Validation: **2 January 2013–30 December 2022**, 2,518 sessions and 120 monthly observations. This is one chronological training/validation split, not repeated rolling walk-forward estimation.
- Reserved final: **3 January 2023–31 December 2025**. Those price observations were **not requested or evaluated**. They are untouched relative to this recorded protocol, not guaranteed unknown to all prior human research.
- Initial capital: USD 100,000 per attempt. Long-only, unlevered, at most 100% gross allocation; uninvested cash earns **0%**.
- Monthly decisions use completed closes; queued targets execute at the following session's adjusted-open proxy. Every policy starts in cash and first signals at an in-period month-end, including the passive references. End holdings remain marked, without an assumed liquidation.
- Six candidate configurations: two families with lookbacks of **126, 189 and 252 sessions**. Within each family, the highest training net excess CAGR selected the lookback before validation. Ties retain declared order. Other validation lookbacks are sensitivity evidence; they did not replace the training-selected configuration.
- Costs: **5, 10 and 20 basis points one way on traded notional**, shared with the relevant benchmarks. These are declared scenarios, not measured spreads or a liquidity model.

The two hypotheses were a monthly SPY long/cash moving-average filter, and monthly allocation to the strongest positive trailing return among SPY/IEF/GLD, otherwise cash. The selected lookbacks were **189 sessions for SPY trend** and **126 for cross-asset momentum**.

The preserved action columns contain **72 nonzero SPY dividend events**, **216 IEF dividend events**, and **zero GLD dividend events**. Each ETF has zero nonzero split or capital-gain entries in this snapshot. Counts were computed directly from the archived adapter frames; zero recorded events is not independent certification of provider completeness.

This is revised Yahoo adjusted-close research. Adjusted opens are derived as `Open × Adj Close / Close`, and the simulator holds fractional normalized total-return proxy units overnight. Distributions are embedded in that proxy and are not credited again. These are **not raw-share fills**, an action/pay-date cash ledger, or executable opening-auction prices. Adapter DataFrames are preserved; original Yahoo HTTP bytes and historical revision vintages are unavailable. Provider metadata includes retrieval-date 2026 quotes/context, even though 2023–2025 historical price rows were not requested; metadata was not used in the signals.

An acquisition-provenance defect was found after this first result: yfinance's metadata mapping serialized as a Python representation **string**, rather than machine-readable fields, in the original raw/manifest files. The original snapshot remains preserved. Live currency/timezone checks and the numeric frame/ledger evidence remain available, but structured metadata needs correction in a new explicitly versioned acquisition. This report does not silently substitute corrected metadata. The first runs record source hashes, rather than a complete bundled source snapshot.

## Selected validation results at 5 basis points

All percentages below refer to the validation period. Drawdown is shown as a positive peak-to-trough loss; exposure is average invested market value divided by equity. Benchmarks use the same start-in-cash/month-end-entry convention and cost model.

| Policy | CAGR | Maximum drawdown | Annualized daily volatility | Average exposure |
| --- | ---: | ---: | ---: | ---: |
| SPY trend, 189 sessions | 8.05% | 23.52% | 12.38% | 83.32% |
| SPY passive reference | 11.83% | 33.72% | 17.36% | 99.17% |
| Cross-asset momentum, 126 sessions | 5.88% | 21.97% | 12.73% | 94.08% |
| Monthly equal-weight SPY/IEF/GLD reference | 4.72% | 17.01% | 8.06% | 99.17% |

SPY trend gave up **3.78 percentage points of annual CAGR** relative to SPY. Its lower drawdown and volatility merit a risk-reduction description; lower exposure and missed gains prevent a return-edge claim. Momentum gained **1.16 points of CAGR** over equal weight, but had a larger drawdown and materially higher volatility. That difference is not estimated factor alpha.

Parameter sensitivity does not resolve the uncertainty: base-cost validation CAGR spans **8.05–8.79%** for the trend family and **3.84–6.95%** for momentum. The validation-best momentum lookback was 189, but the protocol keeps the training-selected 126 rather than switching after seeing these results.

## Cost stress and uncertainty

| One-way cost | Selected SPY trend CAGR | Excess CAGR versus SPY | Selected momentum CAGR | Excess CAGR versus equal weight |
| --- | ---: | ---: | ---: | ---: |
| 5 bps | 8.05% | −3.78 percentage points | 5.88% | +1.16 percentage points |
| 10 bps | 7.97% | −3.85 percentage points | 5.56% | +0.86 percentage points |
| 20 bps | 7.81% | −4.00 percentage points | 4.91% | +0.25 percentage points |

Momentum's advantage is small under higher costs. Its maximum drawdown increases from **21.97% to 23.50%**, and charged proxy costs rise from **USD 4,259.20 to USD 16,241.53** between the 5 and 20 bps scenarios. No extra terminal sale is charged because positions remain marked.

The recorded uncertainty statistic is **annualized mean paired monthly log-return excess**, `12 × mean(log(strategy_month_growth) − log(benchmark_month_growth))`. It is neither a CAGR difference nor factor alpha. The base-cost selected estimates and interval endpoints, in **decimal annual log-return units**, are:

| Selected family | Estimate | Lower endpoint | Upper endpoint |
| --- | ---: | ---: | ---: |
| SPY trend versus SPY | −0.0343183227 | −0.0860161919 | +0.0094318026 |
| Momentum versus equal weight | +0.0109953810 | −0.1096184152 | +0.1112864380 |

Both intervals include zero. The code uses 5,000 paired moving-block resamples with 12-month blocks and seed `20261015`. It sets per-configuration alpha to `0.05 / 6`, giving bootstrap quantiles `0.0041667` and `0.9958333`. The intended Bonferroni adjustment covers the six locally declared distinct protocol/configuration pairs; it cannot correct unknown external searches or remove retrospective universe selection. Stationarity, block choice, limited regimes and bootstrap approximation constrain the interpretation. Full-precision values are in the study artifact.

## Failures, reconciliation and provenance

The first study, `20261015000000000000000000000001`, failed after **three recorded completed attempts** when summary selection accessed a missing `cagr_pct` metric. This was an implementation failure, not a losing market result, and its attempts, source hashes and failure record remain preserved. The corrected implementation reran the **same protocol and exact checksummed snapshot** as study `20261015000000000000000000000002`. It completed **32 attempts**, all with successful independent proxy-ledger reconciliation. There are **35 recorded attempts across the failed and completed studies**, rather than 35 independently tested hypotheses.

The 32 completed attempts comprise eight training configurations/references and eight validation configurations/references at each of three cost rates. Reconciliation checks the declared proxy accounting; it does not verify raw-share accounting or provider truth. Snapshot file checksums were verified for this report. No extra parameter search or new hypothesis evaluation was performed to produce it.

- [Completed study and comparisons](../artifacts/trading/daily-edge-pilot-20261015/completed-output/daily-study.json)
- [Completed summary](../artifacts/trading/daily-edge-pilot-20261015/completed-output/summary.json)
- [Original request](../artifacts/trading/daily-edge-pilot-20261015/request.json)
- [Preregistered corrected run](../artifacts/trading/daily-edge-pilot-20261015/research/daily-studies/20261015000000000000000000000002/preregistered.json)
- [Completed attempt ledger and artifact references](../artifacts/trading/daily-edge-pilot-20261015/research/daily-studies/20261015000000000000000000000002/attempts.jsonl)
- [Preserved failed study](../artifacts/trading/daily-edge-pilot-20261015/research/daily-studies/20261015000000000000000000000001/daily-study.json)
- [Original dataset manifest and checksums](../artifacts/trading/daily-edge-pilot-20261015/research/daily-studies/20261015000000000000000000000001/dataset/manifest.json)
- Original adapter frames: [SPY](../artifacts/trading/daily-edge-pilot-20261015/research/daily-studies/20261015000000000000000000000001/dataset/raw-SPY.json), [IEF](../artifacts/trading/daily-edge-pilot-20261015/research/daily-studies/20261015000000000000000000000001/dataset/raw-IEF.json), [GLD](../artifacts/trading/daily-edge-pilot-20261015/research/daily-studies/20261015000000000000000000000001/dataset/raw-GLD.json).

Dataset ID: `83522468c1ba8dcf4b20e37de78bdbe2b2dc7dc2ccaba6e2617b56a3c87bcecb`.
Protocol ID: `361d429f21851f7e7d862be6c99e77d31a549c515f7a930cfe60f91641d01137`.
These artifacts are local ignored research outputs; a fresh checkout will not contain them automatically.

## Next decision

Keep these strategies **research-only**. Their evidence is inconclusive and does not justify consuming the reserved final period merely to seek a better story. Promotion requires independent-source replication, raw-share corporate-action/cash accounting, a frozen final evaluation and genuinely forward simulated observations. [Data-source exploration and promotion requirements](EDGE_DATA.md)

A separately motivated next hypothesis is **long-only sector ETF momentum**, grounded in industry-level return persistence rather than a tweak chosen from this pilot's winners. Moskowitz and Grinblatt's *Do Industries Explain Momentum?* (1999) studies industry momentum; its long/short industry-stock evidence predates this pilot and does not prove a modern long-only ETF implementation. Before acquiring that universe, preregister its exact eligible ETFs/inception treatment, signal, holding rule, benchmark, costs, search budget and untouched period. No such sector experiment has been run in this report. [Original journal paper](https://onlinelibrary.wiley.com/doi/abs/10.1111/0022-1082.00146), [author publication record](https://faculty.som.yale.edu/tobymoskowitz/research/)

For background, Moskowitz, Ooi and Pedersen's *Time Series Momentum* (2012) concerns futures/forwards across multiple asset classes. Its evidence motivates testing persistence; it does not validate this three-ETF long/cash screen or import leverage, shorting and volatility scaling into it. [Paper and author summary](https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum)

Alternatively, if the next objective is operational validation of these existing hypotheses, acquire an independent historical SIP sample with verified entitlements and build the raw-share ledger first. Do not change the selected rules while calling that replication. No paid access or provider account was created for this report; source links were checked on 16 October 2026.
