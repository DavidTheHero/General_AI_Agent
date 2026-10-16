"""Research-only global reversal report and continuous-validation figures."""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from .reporting import atomic_text


def write_weekly_report(record, directory, output):
    directory, output = Path(directory), Path(output)
    primary = [item for item in record["comparisons"] if item["primary"]]
    lines = ["# Global ETF reversal: declared historical test", "",
        f"Assessment: **{record['assessment']}**. Promotion: **research_only**.", "",
        "Primary L5/K3 ranks nine ETFs by five-session log return divided by sqrt(5) times the sample volatility of exactly 63 prior daily log returns ending before that return window. "
        "It holds the lowest three scores equally. Weekly completed-close targets execute at the next official session's adjusted-open proxy. "
        "The other three configurations are sensitivity only; no winner replaces the primary.", "",
        "Initial development 2008–2012; continuous validation 2013–2022 with five chronological two-year folds. "
        "The primary parameters remain fixed. Prior development target weights determine only each fold's allocation reference. "
        "Capital and holdings do not reset between validation folds. Reserved 2023–2025 historical price paths were not requested or evaluated.", "",
        "| Cost bps / side | Reference | Primary CAGR | Reference CAGR | Excess pp/year | Primary drawdown | Reference drawdown | Evidence |",
        "|---:|---|---:|---:|---:|---:|---:|---|"]
    for item in primary:
        lines.append(f"| {item['cost_bps']:g} | {item['benchmark']} | {item['metrics']['cagr_pct']:.2f}% | "
            f"{item['benchmark_metrics']['cagr_pct']:.2f}% | {item['excess_cagr_percentage_points']:+.2f} | "
            f"{item['metrics']['max_drawdown_pct']:.2f}% | {item['benchmark_metrics']['max_drawdown_pct']:.2f}% | {item['evidence']['assessment']} |")
    lines.extend(["", "All portfolios share USD 100,000, zero-yield cash, a maximum unit gross target and the same per-side costs on traded notional. "
        "Training-allocation matched means average primary target weights from strictly prior expanding development history; it does not match future realized exposures. "
        "The reference switches at the next-open execution of each fold's first eligible target. End holdings are marked without an invented sale.", "",
        "| Cost bps / side | SPY passive CAGR | Role |", "|---:|---:|---|"])
    for cost in record["protocol"]["cost_bps"]:
        item = next(item for item in record["attempts"] if item["period"] == "validation_benchmark" and item["policy"]["kind"] == "buy_hold" and item["cost_bps"] == cost)
        lines.append(f"| {cost:g} | {item['metrics']['cagr_pct']:.2f}% | Context; not a risk-matched alpha hurdle |")
    lines.extend(["", "![Continuous validation wealth and drawdowns](performance.png)", "",
        "## Declared sensitivity, base costs", "", "| Lookback / holdings | CAGR | Drawdown | Role |", "|---|---:|---:|---|"])
    for item in record["attempts"]:
        if item["period"] == "validation" and item["cost_bps"] == 5:
            role = "Primary" if item["policy"] == record["primary_policy"] else "Sensitivity; cannot replace primary"
            lines.append(f"| {item['policy']['lookback']} / {item['policy']['holdings']} | {item['metrics']['cagr_pct']:.2f}% | {item['metrics']['max_drawdown_pct']:.2f}% | {role} |")
    lines.extend(["", "## Continuous primary fold diagnostics, base costs", "",
        "| Fold | Starting equity | Ending equity | Total return | Within-fold drawdown | Mean gross exposure | Costs |",
        "|---|---:|---:|---:|---:|---:|---:|"])
    selected = next(item for item in record["attempts"] if item["period"] == "validation" and item["policy"] == record["primary_policy"] and item["cost_bps"] == 5)
    for fold in selected["fold_diagnostics"]:
        lines.append(f"| {fold['start']}–{fold['end']} | {fold['starting_equity']:.2f} | {fold['ending_equity']:.2f} | "
            f"{fold['return_pct']:+.2f}% | {fold['max_fold_drawdown_pct']:.2f}% | {fold['avg_exposure_pct']:.2f}% | {fold['total_cost']:.2f} |")
    lines.extend(["", "Allocation weights, mean observed asset exposures, concentration, turnover, all fold diagnostics and uncertainty endpoints are recorded in daily-study.json. "
        "Paired monthly uncertainty uses 12-month moving blocks, 5,000 draws, seed 20261015 and a correction across at least 14 known configurations. "
        "Costs, folds, references and repeated runs are dependent views; this is neither factor alpha nor a calibrated probability of an edge.", "",
        "**Data and execution limits:** These are normalized fractional total-return research units, not raw-share orders. "
        "Revised adjusted series embed provider reinvestment conventions; corporate actions and payment-date cash remain operational blockers. "
        "International ETF closes can reflect stale underlying-market prices and asynchronous holidays. Commodity-fund returns contain roll, collateral and expense effects. "
        "The fixed surviving universe, historical researcher/LLM knowledge, unknown historical spreads/auction liquidity and unmodeled taxes remain limitations. "
        "Fixed 5/10/20-bps costs are assumptions, not measured execution evidence.", "",
        f"Dataset: `{record['dataset_id']}`", "", f"Protocol: `{record['protocol_id']}`", "",
        f"Experiment: `{record['experiment_id']}`; {len(record['attempts'])} completed/reconciled proxy-ledger attempts.", "",
        "Promotion blockers: " + "; ".join(record["promotion_blockers"]) + "."])
    atomic_text(output / "report.md", "\n".join(lines) + "\n")
    figure, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True, gridspec_kw={"height_ratios": [2, 1]})
    attempts = [(selected["attempt_id"], "Primary L5/K3", "#2563eb")]
    for kind, label, color in [("equal_weight", "Equal-weight nine ETFs", "#16a34a"),
                               ("training_allocation", "Prior-training allocation", "#9333ea"), ("buy_hold", "SPY passive", "#6b7280")]:
        item = next(item for item in record["attempts"] if item["period"] == "validation_benchmark" and item["policy"]["kind"] == kind and item["cost_bps"] == 5)
        attempts.append((item["attempt_id"], label, color))
    for identifier, label, color in attempts:
        rows = json.loads((directory / f"{identifier}.json").read_text())["result"]["rows"]
        dates = pd.to_datetime([row["date"] for row in rows])
        axes[0].plot(dates, [row["equity"] / 1000 for row in rows], label=label, color=color, linewidth=1.2)
        axes[1].plot(dates, [-row["drawdown_pct"] for row in rows], color=color, linewidth=1)
    for fold in record["validation_folds"][1:]:
        for axis in axes:
            axis.axvline(pd.Timestamp(fold["start"]), color="#64748b", alpha=.25, linewidth=.8)
    axes[0].set_ylabel("Proxy wealth (USD thousands)")
    axes[1].set_ylabel("Continuous drawdown (%)")
    axes[0].legend(fontsize=9)
    for axis in axes:
        axis.grid(alpha=.2)
    figure.suptitle(f"2013–2022 continuous validation · 5 bps per side · {record['assessment']}")
    figure.tight_layout()
    figure.savefig(output / "performance.png", dpi=160)
    plt.close(figure)
