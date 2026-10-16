"""Offline end-to-end verification: synthetic observations never establish an edge.

Run from the repository root: .venv/bin/python -m examples.research_workflow --output artifacts/trading/research-verification
"""
import argparse
import json
from pathlib import Path
from uuid import uuid4

from trading_agent.config import AgentConfig, StrategyConfig
from trading_agent.datasets import DatasetStore, canonical
from trading_agent.research import ExperimentSpec, run_experiment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        parser.error("Use a new output directory to preserve previous evidence")
    args.output.mkdir(parents=True, exist_ok=True)
    root = args.output / "research"
    request = {"source": "synthetic", "symbols": ["DEMO_A"], "start": "2026-09-01", "end": "2026-09-14", "interval": "30m", "seed": 17}
    (args.output / "dataset-request.json").write_text(canonical({"mode": "dataset", "dataset": request}))
    manifest = DatasetStore(root / "datasets").acquire(request)
    spec = ExperimentSpec(dataset_id=manifest["dataset_id"], config=AgentConfig(symbols=request["symbols"], interval=request["interval"]),
        candidates=[StrategyConfig(kind="trend_following", fast_window=2, slow_window=4),
                    StrategyConfig(kind="trend_following", fast_window=3, slow_window=6),
                    StrategyConfig(kind="mean_reversion", slow_window=4),
                    StrategyConfig(kind="opening_range_breakout", opening_range_bars=2)],
        train_sessions=2, validation_sessions=2, final_sessions=2)
    validation_id, final_id = uuid4().hex, uuid4().hex
    (args.output / "validation-request.json").write_text(canonical({"mode": "experiment", "experiment": spec.model_dump()}))
    validation = run_experiment(spec, root, args.output / "validation", validation_id)
    if validation["status"] != "complete":
        raise RuntimeError(f"Validation failed: {validation['errors']}")
    final_spec = spec.model_copy(update={"finalize": True, "parent_experiment_id": validation_id})
    (args.output / "final-request.json").write_text(canonical({"mode": "experiment", "experiment": final_spec.model_dump()}))
    final = run_experiment(final_spec, root, args.output / "final", final_id)
    attempts = validation["attempts"] + final["attempts"]
    if final["status"] != "complete" or not all(attempt["reconciliation"]["ok"] for attempt in attempts):
        raise RuntimeError(f"Final evaluation or ledger reconciliation failed: {final['errors']}")
    summary = {"source": manifest["source"], "dataset_id": manifest["dataset_id"], "validation_id": validation_id,
               "final_id": final_id, "attempts": len(attempts), "reconciled_attempts": len(attempts),
               "assessment": final["assessment"], "assessment_reason": final["assessment_reason"],
               "final_metrics": final["metrics"], "artifact_root": str(args.output.resolve())}
    (args.output / "verification.json").write_text(canonical(summary))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
