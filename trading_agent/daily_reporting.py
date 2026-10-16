"""Export inspected daily research evidence; no performance claims from a model."""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from .reporting import atomic_text


def write_daily_report(record, directory, output):
    directory, output = Path(directory), Path(output)
    selected = [item for item in record["comparisons"] if item["selected_by_training"]]
    lines = ["# Daily ETF edge research", "", f"Assessment: **{record['assessment']}**. Promotion: **research_only**.", "",
        "Real Yahoo daily observations; normalized fractional total-return proxy units. These are not raw-share execution results.", "",
        f"Training: {record['protocol']['development_start']} to the session before {record['protocol']['validation_start']}. "
        f"Validation: {record['protocol']['validation_start']} to {record['protocol']['development_end']}.", "",
        f"Reserved final prices {record['reserved_final']['start']} through {record['reserved_final']['end']} were not requested.", "",
        "| Frozen policy | Cost bps / side | Net CAGR | Benchmark CAGR | Max drawdown | Benchmark drawdown | Evidence |",
        "|---|---:|---:|---:|---:|---:|---|"]
    for item in selected:
        lines.append(f"| {item['policy']['kind']} ({item['policy']['lookback']}) | {item['cost_bps']:g} | "
            f"{item['metrics']['cagr_pct']:.2f}% | {item['benchmark_metrics']['cagr_pct']:.2f}% | "
            f"{item['metrics']['max_drawdown_pct']:.2f}% | {item['benchmark_metrics']['max_drawdown_pct']:.2f}% | {item['evidence']['assessment']} |")
    lines.extend(["", "Positive profit, excess return and improved risk control are separate outcomes. Paired block-bootstrap intervals, "
        "sensitivity attempts and chronological validation subperiods are in daily-study.json. This is a fixed train/validation study, not rolling retraining.", "",
        "![Validation equity and drawdowns](performance.png)", "", f"Dataset: `{record['dataset_id']}`", "",
        f"Protocol: `{record['protocol_id']}`", "", f"Attempts: {len(record['attempts'])}; all completed proxy ledgers reconciled.", "",
        "The same month-end entry opportunities, zero cash yield, declared capital and cost conventions apply to strategies and benchmarks. "
        "End holdings are marked without an invented exit. Historical data, a retrospectively chosen surviving universe and researcher knowledge can bias results.", "",
        "Promotion blockers: " + "; ".join(record["promotion_blockers"]) + "."])
    atomic_text(output / "report.md", "\n".join(lines) + "\n")

    figure, axes = plt.subplots(2, 2, figsize=(13, 7), sharex="col", gridspec_kw={"height_ratios": [2, 1]})
    base = record["protocol"]["cost_bps"][0]
    for column, family in enumerate(["sma_cash", "relative_momentum"]):
        item = next(item for item in selected if item["policy"]["kind"] == family and item["cost_bps"] == base)
        benchmark = next(attempt for attempt in record["attempts"] if attempt["period"] == "validation_benchmark"
                         and attempt["policy"]["kind"] == item["benchmark"] and attempt["cost_bps"] == base)
        for attempt_id, label, color in [(item["attempt_id"], f"{family} ({item['policy']['lookback']})", "#2563eb"),
                                         (benchmark["attempt_id"], item["benchmark"], "#6b7280")]:
            result = json.loads((directory / f"{attempt_id}.json").read_text())["result"]
            dates = pd.to_datetime([row["date"] for row in result["rows"]])
            axes[0, column].plot(dates, [row["equity"] / 1000 for row in result["rows"]], label=label, color=color, linewidth=1.2)
            axes[1, column].plot(dates, [-row["drawdown_pct"] for row in result["rows"]], color=color, linewidth=1)
        axes[0, column].set_title(f"{family} versus its declared benchmark")
        axes[0, column].set_ylabel("Proxy wealth (USD thousands)")
        axes[1, column].set_ylabel("Drawdown (%)")
        axes[0, column].legend(fontsize=8)
        for row in range(2):
            axes[row, column].grid(alpha=.2)
    figure.suptitle(f"Historical validation · {base:g} bps per traded dollar · no validated edge", fontsize=13)
    figure.tight_layout()
    figure.savefig(output / "performance.png", dpi=160)
    plt.close(figure)
