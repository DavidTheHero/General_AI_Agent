"""Four frozen global ETF reversal trials with causal expanding allocation references."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
from typing import Literal

import numpy as np
from pydantic import Field, model_validator
import yfinance as yf

from .config import Settings
from .daily_research import acquire_daily_observations, load_daily, paired_evidence
from .daily_screen import reconcile_daily_proxy
from .datasets import canonical, checksum, utcnow
from .reporting import atomic_text
from .weekly_screen import WEEKLY_UNIVERSE, WeeklyReversalPolicySpec, simulate_weekly_reversal


FOLDS = (("2013-01-02", "2014-12-31"), ("2015-01-02", "2016-12-31"),
         ("2017-01-03", "2018-12-31"), ("2019-01-02", "2020-12-31"),
         ("2021-01-04", "2022-12-30"))


class WeeklyResearchSpec(Settings):
    source: Literal["yahoo"] = "yahoo"
    symbols: list[str] = Field(default_factory=lambda: list(WEEKLY_UNIVERSE), min_length=9, max_length=9)
    data_start: Literal["2007-01-03"] = "2007-01-03"
    development_start: Literal["2008-01-02"] = "2008-01-02"
    validation_start: Literal["2013-01-02"] = "2013-01-02"
    development_end: Literal["2022-12-30"] = "2022-12-30"
    reserved_final_start: Literal["2023-01-03"] = "2023-01-03"
    reserved_final_end: Literal["2025-12-31"] = "2025-12-31"
    initial_cash: Literal[100000.0] = 100000.0
    cost_bps: list[float] = Field(default_factory=lambda: [5.0, 10.0, 20.0], min_length=3, max_length=3)

    @model_validator(mode="after")
    def frozen_protocol(self):
        if self.symbols != list(WEEKLY_UNIVERSE) or self.cost_bps != [5.0, 10.0, 20.0]:
            raise ValueError("Global reversal freezes the nine-ETF universe/order and costs [5,10,20]; changes need a new declaration")
        return self


def allocation_reference(result, fold_start, training_end, attempt_id):
    """Mean prior target weights, without using fills, returns or validation prices."""
    decisions = result["decisions"]
    if not decisions:
        raise ValueError("Allocation reference requires completed prior primary decisions")
    totals = {symbol: 0.0 for symbol in WEEKLY_UNIVERSE}
    for decision in decisions:
        if not "2008-01-02" <= decision["date"] <= training_end or decision["date"] >= fold_start:
            raise ValueError("Allocation reference contains a decision outside strictly prior development history")
        if decision["completed_observations"] < 69:
            raise ValueError("Allocation reference contains an insufficiently warmed primary decision")
        weights = decision["weights"]
        if set(weights) != set(WEEKLY_UNIVERSE) or any(isinstance(weight, bool) or not isinstance(weight, (int, float))
                or not math.isfinite(weight) or weight < 0 for weight in weights.values()) or not math.isclose(sum(weights.values()), 1.0, rel_tol=0, abs_tol=1e-10):
            raise ValueError("Allocation reference requires exact-universe finite long-only unit-gross targets")
        for symbol, weight in weights.items():
            totals[symbol] += weight
    return {"fold_start": fold_start, "training_start": "2008-01-02", "training_end": training_end,
            "source_attempt_id": attempt_id, "decisions": len(decisions), "latest_decision": max(item["date"] for item in decisions),
            "weights": {symbol: total / len(decisions) for symbol, total in totals.items()},
            "activation": "next_session_open", "method": "Arithmetic mean of primary prior completed-close target weights; no validation weights or returns"}


def fold_diagnostics(result):
    """Slice one continuous ledger; never reset or compound a different portfolio."""
    diagnostics = []
    prior_equity = result["metrics"]["initial_equity"]
    for start, end in FOLDS:
        rows = [row for row in result["rows"] if start <= row["date"] <= end]
        if not rows:
            raise ValueError("Continuous validation ledger omits a declared fold")
        before = [row for row in result["rows"] if row["date"] < start]
        baseline = before[-1]["equity"] if before else prior_equity
        peak, worst, previous, returns = baseline, 0.0, baseline, []
        for row in rows:
            peak = max(peak, row["equity"])
            worst = max(worst, 1 - row["equity"] / peak)
            returns.append(row["equity"] / previous - 1)
            previous = row["equity"]
        diagnostics.append({"start": start, "end": end, "first_observation": rows[0]["date"], "last_observation": rows[-1]["date"],
            "starting_equity": baseline, "ending_equity": rows[-1]["equity"], "return_pct": (rows[-1]["equity"] / baseline - 1) * 100,
            "max_fold_drawdown_pct": worst * 100, "annualized_volatility_pct": float(np.std(returns, ddof=1) * math.sqrt(252) * 100) if len(rows) >= 30 else None,
            "total_cost": sum(row["cost"] for row in rows), "gross_turnover": sum(row["turnover"] for row in rows),
            "avg_exposure_pct": sum(sum(row["weights"].values()) for row in rows) / len(rows) * 100,
            "mean_asset_weights": {symbol: sum(row["weights"][symbol] for row in rows) / len(rows) for symbol in WEEKLY_UNIVERSE},
            "maximum_observed_position_weight": max(max(row["weights"].values()) for row in rows), "sessions": len(rows)})
    return diagnostics


def run_weekly_research(spec, root, output, experiment_id, *, ticker_factory=yf.Ticker):
    from .research import _environment
    spec = WeeklyResearchSpec.model_validate(spec)
    if not re.fullmatch(r"[a-f0-9]{32}", experiment_id):
        raise ValueError("Use an exact experiment ID")
    root, output = Path(root), Path(output)
    directory = root / "daily-studies" / experiment_id
    directory.mkdir(parents=True, exist_ok=False)
    output.mkdir(parents=True, exist_ok=True)
    source = directory / "source"
    source.mkdir()
    for path in Path(__file__).parent.glob("*.py"):
        target = source / path.name
        target.write_bytes(path.read_bytes())
        target.chmod(0o444)
    declaration = Path(__file__).parent.parent / "docs" / "GLOBAL_REVERSAL_PROTOCOL.md"
    captured_declaration = directory / "declared-protocol.md"
    captured_declaration.write_bytes(declaration.read_bytes())
    captured_declaration.chmod(0o444)
    grid = [WeeklyReversalPolicySpec(kind="weekly_reversal", lookback=lookback, holdings=holdings)
            for lookback in [1, 5] for holdings in [1, 3]]
    primary_policy = WeeklyReversalPolicySpec(kind="weekly_reversal", lookback=5, holdings=3)
    protocol = {"declaration": "declared-protocol.md", "declaration_sha256": checksum(captured_declaration),
                "hypothesis_version": "global_weekly_reversal_v1", "settings": spec.model_dump(),
                "configurations": [policy.model_dump() for policy in grid], "primary": primary_policy.model_dump(), "validation_folds": FOLDS}
    protocol_id = hashlib.sha256(canonical(protocol).encode()).hexdigest()
    record = {"schema_version": "weekly-study-1.0.0", "hypothesis_id": "global_weekly_reversal_v1", "experiment_id": experiment_id,
              "protocol_id": protocol_id, "protocol": spec.model_dump(), "candidate_grid": protocol["configurations"], "primary_policy": protocol["primary"],
              "status": "running", "generated_at": utcnow(), "source": "Yahoo development-data acquisition pending",
              "assessment": "inconclusive", "promotion_status": "research_only", "attempts": [], "comparisons": [], "metrics": {}, "errors": [],
              "environment": _environment(), "source_snapshot": {path.name: checksum(path) for path in source.iterdir()},
              "reserved_final": {"start": spec.reserved_final_start, "end": spec.reserved_final_end, "accessed": False},
              "selection_rule": "Primary L5/K3 fixed before acquisition; three sensitivity configurations never replace it. Only reference allocations use expanding strictly prior targets.",
              "promotion_blockers": ["Adjusted total-return proxy, no raw-share/payment-date ledger", "Independent data replication missing",
                  "Historical quote/auction execution costs unmeasured", "Reserved final evaluation not performed", "No genuinely forward paper observations"],
              "accounting": "Completed ISO-week-end targets, next-session adjusted-open proxy, continuous overnight fractional units, zero-yield cash, shared per-side costs",
              "allocation_references": [], "spy_context": [], "validation_folds": [{"start": start, "end": end} for start, end in FOLDS]}
    if record["source_snapshot"] != record["environment"]["source_sha256"]:
        raise ValueError("Research source changed during capture")
    atomic_text(directory / "preregistered.json", canonical({**protocol, "environment": record["environment"], "recorded_at": utcnow()}))
    database = sqlite3.connect(root / "daily-studies.sqlite", timeout=30)
    database.execute("CREATE TABLE IF NOT EXISTS reservations (universe TEXT PRIMARY KEY, start TEXT, end TEXT)")
    database.execute("CREATE TABLE IF NOT EXISTS studies (id TEXT PRIMARY KEY, protocol TEXT, status TEXT)")
    database.execute("INSERT INTO studies VALUES (?,?,?)", (experiment_id, canonical(record), "running"))
    database.commit()

    def save():
        record["generated_at"] = utcnow()
        atomic_text(directory / "daily-study.json", canonical(record))
        atomic_text(output / "daily-study.json", canonical(record))
        summary = {key: record.get(key) for key in ["status", "generated_at", "source", "metrics", "errors", "experiment_id", "protocol_id", "assessment", "promotion_status", "provenance_ref"]}
        atomic_text(output / "summary.json", canonical(summary))
        database.execute("UPDATE studies SET protocol=?,status=? WHERE id=?", (canonical(record), record["status"], experiment_id))
        database.commit()

    def event(name, item):
        with (directory / "attempts.jsonl").open("a") as stream:
            stream.write(canonical({"event": name, **item}) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def attempt(policy, period, start, end, cost, *, allocation_by_fold=None):
        identifier = f"{experiment_id}-{len(record['attempts']) + 1:04}"
        item = {"attempt_id": identifier, "policy": policy.model_dump(), "period": period, "start": start, "end": end,
                "cost_bps": cost, "status": "running", "artifact_ref": f"daily-studies/{experiment_id}/{identifier}.json", "metrics": {}}
        record["attempts"].append(item)
        event("started", item)
        save()
        result = simulate_weekly_reversal(frames, policy, start, end, cost_bps=cost, initial_cash=spec.initial_cash,
                                          allocation_by_fold=allocation_by_fold)
        reconciliation = reconcile_daily_proxy(result, frames)
        if not reconciliation["ok"]:
            raise ValueError("Weekly proxy reconciliation failed: " + "; ".join(reconciliation["errors"]))
        item.update(status="complete", metrics=result["metrics"], reconciliation=reconciliation)
        if period.startswith("validation"):
            item["fold_diagnostics"] = fold_diagnostics(result)
        atomic_text(directory / f"{identifier}.json", canonical({"attempt": item, "result": result}))
        event("completed", item)
        atomic_text(output / "progress.json", canonical({"state": "weekly_research", "attempt_id": identifier,
            "attempts_completed": len(record["attempts"]), "attempts_planned": 31, "period": period}))
        save()
        return item, result

    save()
    try:
        with database:
            universe = canonical(spec.symbols)
            database.execute("INSERT OR IGNORE INTO reservations VALUES (?,?,?)", (universe, spec.reserved_final_start, spec.reserved_final_end))
            if database.execute("SELECT start,end FROM reservations WHERE universe=?", (universe,)).fetchone() != (spec.reserved_final_start, spec.reserved_final_end):
                raise ValueError("This universe already reserves a different final period")
        cached = None
        for path in sorted((root / "daily-studies").glob("*/dataset/manifest.json")):
            candidate = json.loads(path.read_text())
            request = candidate["request"]
            settings_match = all(request.get(key) == value for key, value in {
                "symbols": spec.symbols, "start": spec.data_start, "end_exclusive": "2022-12-31", "interval": "1d",
                "auto_adjust": False, "back_adjust": False, "actions": True, "repair": False, "keepna": True,
                "prepost": False, "rounding": False}.items())
            if settings_match and candidate["quality"]["usable"] and all(isinstance(candidate.get("metadata", {}).get(symbol), dict)
                    and "fields" in candidate["metadata"][symbol] for symbol in spec.symbols):
                cached = path.parent
                break
        data_directory = cached or directory / "dataset"
        frames, manifest = load_daily(cached) if cached else acquire_daily_observations(spec, data_directory, ticker_factory=ticker_factory)
        record.update(source=manifest["source"], dataset_id=manifest["dataset_id"], data_quality=manifest["quality"],
                      provenance_ref=str(data_directory.relative_to(root) / "manifest.json"),
                      data_acquisition="Exact checksummed snapshot reused with original retrieval date" if cached else "New explicit development-only acquisition")
        atomic_text(output / "data-manifest.json", canonical(manifest))
        benchmarks = [WeeklyReversalPolicySpec(kind="equal_weight"), WeeklyReversalPolicySpec(kind="buy_hold")]
        initial_primary = None
        for policy in benchmarks + grid:
            evaluated = attempt(policy, "training_benchmark" if policy.kind != "weekly_reversal" else "training", spec.development_start, "2012-12-31", 5.0)
            if policy == primary_policy:
                initial_primary = evaluated
        references = [allocation_reference(initial_primary[1], FOLDS[0][0], "2012-12-31", initial_primary[0]["attempt_id"])]
        for index, (fold_start, _) in enumerate(FOLDS[1:], start=1):
            training_end = FOLDS[index - 1][1]
            item, result = attempt(primary_policy, "allocation_training", spec.development_start, training_end, 5.0)
            references.append(allocation_reference(result, fold_start, training_end, item["attempt_id"]))
        record["allocation_references"] = references
        allocation_by_fold = {reference["fold_start"]: reference["weights"] for reference in references}
        save()
        configurations = set()
        for (text,) in database.execute("SELECT protocol FROM studies"):
            prior = json.loads(text)
            if "candidate_grid" in prior:
                configurations.update((prior["protocol_id"], canonical(policy)) for policy in prior["candidate_grid"])
            elif "lookbacks" in prior.get("protocol", {}):
                configurations.update((prior["protocol_id"], kind, lookback) for kind in ["sma_cash", "relative_momentum"] for lookback in prior["protocol"]["lookbacks"])
        search_count = max(14, len(configurations))
        for cost in spec.cost_bps:
            evaluated_references = {policy.kind: attempt(policy, "validation_benchmark", spec.validation_start, spec.development_end, cost)[1] for policy in benchmarks}
            allocation_policy = WeeklyReversalPolicySpec(kind="training_allocation")
            evaluated_references["training_allocation"] = attempt(allocation_policy, "validation_benchmark", spec.validation_start, spec.development_end, cost,
                                                                   allocation_by_fold=allocation_by_fold)[1]
            for policy in grid:
                item, result = attempt(policy, "validation", spec.validation_start, spec.development_end, cost)
                for kind in ["equal_weight", "training_allocation"]:
                    benchmark = evaluated_references[kind]
                    record["comparisons"].append({"attempt_id": item["attempt_id"], "policy": policy.model_dump(), "primary": policy == primary_policy,
                        "cost_bps": cost, "metrics": result["metrics"], "benchmark": kind, "benchmark_metrics": benchmark["metrics"],
                        "excess_cagr_percentage_points": result["metrics"]["cagr_pct"] - benchmark["metrics"]["cagr_pct"],
                        "evidence": paired_evidence(result, benchmark, configurations=search_count)})
                if policy == primary_policy:
                    record["spy_context"].append({"attempt_id": item["attempt_id"], "cost_bps": cost,
                        "benchmark_metrics": evaluated_references["buy_hold"]["metrics"],
                        "excess_cagr_percentage_points": result["metrics"]["cagr_pct"] - evaluated_references["buy_hold"]["metrics"]["cagr_pct"],
                        "role": "Context only; SPY CAGR is not a risk-matched alpha hurdle"})
                save()
        primary = [item for item in record["comparisons"] if item["primary"]]
        outcomes = [item["evidence"]["assessment"] for item in primary]
        record["assessment"] = "promising_requires_replication" if all(outcome == "promising_requires_replication" for outcome in outcomes) else "rejects_alpha_claim" if all(outcome == "rejects_alpha_claim" for outcome in outcomes) else "inconclusive"
        record["assessment_reason"] = "Unchanged L5/K3 is compared with weekly equal-weight and strictly prior training-allocation references across costs; concentration, regime dependence and execution assumptions remain material."
        record["multiple_testing"] = {"weekly_configurations": 4, "known_prior_configurations": 10, "local_protocol_configuration_pairs": len(configurations),
            "correction_configurations": search_count, "warning": "Configurations, folds, costs and references overlap; retrospective selection and unknown external searches preclude calibrated edge probabilities"}
        record["metrics"] = {"attempts": len(record["attempts"]), "primary_validation_results": [{"policy": item["policy"], "cost_bps": item["cost_bps"],
            "benchmark": item["benchmark"], "cagr_pct": item["metrics"]["cagr_pct"], "benchmark_cagr_pct": item["benchmark_metrics"]["cagr_pct"],
            "max_drawdown_pct": item["metrics"].get("max_drawdown_pct"), "total_cost": item["metrics"].get("total_cost"),
            "excess_cagr_percentage_points": item["excess_cagr_percentage_points"], "assessment": item["evidence"]["assessment"]} for item in primary]}
        record["status"] = "complete"
        from .weekly_reporting import write_weekly_report
        write_weekly_report(record, directory, output)
    except (Exception, KeyboardInterrupt) as error:
        record["status"] = "cancelled" if isinstance(error, KeyboardInterrupt) else "failed"
        record["errors"].append(str(error) or type(error).__name__)
        for item in record["attempts"]:
            if item["status"] == "running":
                item.update(status=record["status"], error=str(error) or type(error).__name__, artifact_available=False)
                event("terminated", item)
    finally:
        try:
            save()
        finally:
            database.close()
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ["request", "root", "output"]:
        parser.add_argument(f"--{flag}", type=Path, required=True)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--runtime-worker", action="store_true")
    args = parser.parse_args(argv)
    from .worker_control import install_worker_control
    install_worker_control(args.runtime_worker)
    spec = WeeklyResearchSpec.model_validate(json.loads(args.request.read_text(encoding="utf-8"))["weekly_research"])
    record = run_weekly_research(spec, args.root, args.output, args.experiment_id)
    print(canonical({key: record[key] for key in ["experiment_id", "status", "assessment", "metrics", "errors"]}))
    return 0 if record["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
