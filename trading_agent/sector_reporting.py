"""Artifacts for the frozen sector hypothesis, including unsuccessful results."""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from .reporting import atomic_text


def write_sector_report(record, directory, output):
    directory, output = Path(directory), Path(output)
    primary = [item for item in record["comparisons"] if item["primary"]]
    lines = ["# Sector momentum: declared historical test", "",
        f"Assessment: **{record['assessment']}**. Promotion: **research_only**.", "",
        "Primary rule: rank the original nine sector ETFs by AdjClose[t-21] / AdjClose[t-252] - 1; "
        "hold the top three equally, rebalance after completed month-end at the next session's adjusted-open proxy. "
        "The other three declared configurations are sensitivity checks; no winner replaces the primary.", "",
        "Training 2001–2012; fixed-parameter validation 2013–2022. No rolling retraining. "
        "Reserved 2023–2025 historical price paths were not requested or evaluated.", "",
        "| Cost bps / side | Benchmark | Primary CAGR | Benchmark CAGR | Excess pp/year | Primary drawdown | Benchmark drawdown | Evidence |",
        "|---:|---|---:|---:|---:|---:|---:|---|"]
    for item in primary:
        lines.append(f"| {item['cost_bps']:g} | {item['benchmark']} | {item['metrics']['cagr_pct']:.2f}% | "
            f"{item['benchmark_metrics']['cagr_pct']:.2f}% | {item['excess_cagr_percentage_points']:.2f} | "
            f"{item['metrics']['max_drawdown_pct']:.2f}% | {item['benchmark_metrics']['max_drawdown_pct']:.2f}% | {item['evidence']['assessment']} |")
    lines.extend(["", "These are normalized fractional total-return research units, not executable raw-share fills. "
        "All portfolios share USD100,000, zero-yield cash and the same per-side traded-notional costs. "
        "Both passive references enter at the same monthly opportunity. End holdings are marked without an invented exit.", "",
        "![Validation wealth and drawdowns](performance.png)", "",
        "The paired monthly block bootstrap uses 12-month blocks, 5,000 draws and at least ten known searched configurations. "
        "Intervals and chronological two-year diagnostics are in daily-study.json; they are not factor alpha or a calibrated probability of an edge. "
        "Retrospective universe choice, historical model/researcher knowledge, revised adjustments and unmeasured historical spreads remain limitations.", "",
        "**Corporate-action caveat:** XLF's 2016 in-kind distribution of XLRE shares requires independent reconciliation. "
        "The archived provider observations are preserved without repair or substitution.", "",
        f"Dataset: `{record['dataset_id']}`", "", f"Protocol: `{record['protocol_id']}`", "",
        f"Experiment: `{record['experiment_id']}`; {len(record['attempts'])} completed/reconciled proxy-ledger attempts.", "",
        "Promotion blockers: " + "; ".join(record["promotion_blockers"]) + "."])
    atomic_text(output / "report.md", "\n".join(lines) + "\n")
    figure, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True, gridspec_kw={"height_ratios": [2, 1]})
    selected = next(item for item in primary if item["cost_bps"] == 5)
    attempts = [(selected["attempt_id"], "Primary L252/K3", "#2563eb")]
    for kind, label, color in [("sector_equal_weight", "Equal-weight nine sectors", "#16a34a"), ("buy_hold", "SPY passive", "#6b7280")]:
        item = next(item for item in record["attempts"] if item["period"] == "validation_benchmark" and item["policy"]["kind"] == kind and item["cost_bps"] == 5)
        attempts.append((item["attempt_id"], label, color))
    for identifier, label, color in attempts:
        rows = json.loads((directory / f"{identifier}.json").read_text())["result"]["rows"]
        dates = pd.to_datetime([row["date"] for row in rows])
        axes[0].plot(dates, [row["equity"] / 1000 for row in rows], label=label, color=color, linewidth=1.2)
        axes[1].plot(dates, [-row["drawdown_pct"] for row in rows], color=color, linewidth=1)
    axes[0].set_ylabel("Proxy wealth (USD thousands)")
    axes[1].set_ylabel("Drawdown (%)")
    axes[0].legend(fontsize=9)
    for axis in axes:
        axis.grid(alpha=.2)
    figure.suptitle(f"2013–2022 validation · 5 bps per side · {record['assessment']}")
    figure.tight_layout()
    figure.savefig(output / "performance.png", dpi=160)
    plt.close(figure)
