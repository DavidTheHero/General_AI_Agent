"""The four locally declared sector-momentum trials; historical proxy research only."""
import argparse
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from typing import Literal

from pydantic import Field, model_validator
import yfinance as yf

from .config import Settings
from .daily_research import acquire_daily_observations, load_daily, paired_evidence
from .daily_screen import SECTOR_UNIVERSE, SectorPolicySpec, reconcile_daily_proxy, simulate_sector_daily
from .datasets import canonical, checksum, frame_record, utcnow
from .reporting import atomic_text


class SectorResearchSpec(Settings):
    source: Literal["yahoo"] = "yahoo"
    symbols: list[str] = Field(default_factory=lambda: list(SECTOR_UNIVERSE), min_length=10, max_length=10)
    data_start: Literal["2000-01-03"] = "2000-01-03"
    development_start: Literal["2001-01-02"] = "2001-01-02"
    validation_start: Literal["2013-01-02"] = "2013-01-02"
    development_end: Literal["2022-12-30"] = "2022-12-30"
    reserved_final_start: Literal["2023-01-03"] = "2023-01-03"
    reserved_final_end: Literal["2025-12-31"] = "2025-12-31"
    initial_cash: Literal[100000.0] = 100000.0
    cost_bps: list[float] = Field(default_factory=lambda: [5.0, 10.0, 20.0], min_length=3, max_length=3)

    @model_validator(mode="after")
    def frozen_protocol(self):
        if self.symbols != list(SECTOR_UNIVERSE) or self.cost_bps != [5.0, 10.0, 20.0]:
            raise ValueError("This protocol freezes the nine-sector universe plus SPY and costs [5,10,20]; changes need a new declaration")
        return self


def run_sector_research(spec, root, output, experiment_id, *, ticker_factory=yf.Ticker):
    from .research import _environment
    spec = SectorResearchSpec.model_validate(spec)
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
    declaration = Path(__file__).parent.parent / "docs" / "NEXT_EDGE_PROTOCOL.md"
    captured_declaration = directory / "declared-protocol.md"
    captured_declaration.write_bytes(declaration.read_bytes())
    captured_declaration.chmod(0o444)
    grid = [SectorPolicySpec(kind="sector_momentum", lookback=lookback, holdings=holdings) for lookback in [126, 252] for holdings in [1, 3]]
    protocol = {"declaration": "declared-protocol.md", "declaration_sha256": checksum(captured_declaration), "hypothesis_version": "sector_momentum_v1",
                "settings": spec.model_dump(), "configurations": [policy.model_dump() for policy in grid],
                "primary": SectorPolicySpec(kind="sector_momentum", lookback=252, holdings=3).model_dump()}
    protocol_id = hashlib.sha256(canonical(protocol).encode()).hexdigest()
    record = {"schema_version": "sector-study-1.0.0", "hypothesis_id": "sector_momentum_v1", "experiment_id": experiment_id,
              "protocol_id": protocol_id, "protocol": spec.model_dump(), "candidate_grid": protocol["configurations"], "primary_policy": protocol["primary"],
              "status": "running", "generated_at": utcnow(), "source": "Yahoo development-data acquisition pending",
              "assessment": "inconclusive", "promotion_status": "research_only", "attempts": [], "comparisons": [], "metrics": {}, "errors": [],
              "environment": _environment(), "source_snapshot": {path.name: checksum(path) for path in source.iterdir()},
              "reserved_final": {"start": spec.reserved_final_start, "end": spec.reserved_final_end, "accessed": False},
              "selection_rule": "Primary L252/K3 declared before acquisition; other three configurations are sensitivity only. No training or validation winner replaces it.",
              "promotion_blockers": ["Adjusted total-return proxy, no raw-share/payment-date ledger", "Independent data replication missing",
                  "XLF 2016 in-kind XLRE distribution needs independent action reconciliation", "Reserved final evaluation not performed", "No genuinely forward paper observations"],
              "accounting": "Completed month-end targets, next-session adjusted-open proxy, overnight normalized fractional units, zero-yield cash, shared costs"}
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

    def attempt(policy, period, start, end, cost):
        identifier = f"{experiment_id}-{len(record['attempts']) + 1:04}"
        item = {"attempt_id": identifier, "policy": policy.model_dump(), "period": period, "start": start, "end": end,
                "cost_bps": cost, "status": "running", "artifact_ref": f"daily-studies/{experiment_id}/{identifier}.json", "metrics": {}}
        record["attempts"].append(item)
        event("started", item)
        save()
        result = simulate_sector_daily(frames, policy, start, end, cost_bps=cost, initial_cash=spec.initial_cash)
        reconciliation = reconcile_daily_proxy(result, frames)
        if not reconciliation["ok"]:
            raise ValueError("Sector proxy reconciliation failed: " + "; ".join(reconciliation["errors"]))
        item.update(status="complete", metrics=result["metrics"], reconciliation=reconciliation)
        atomic_text(directory / f"{identifier}.json", canonical({"attempt": item, "result": result}))
        event("completed", item)
        atomic_text(output / "progress.json", canonical({"state": "sector_research", "attempt_id": identifier,
            "attempts_completed": len(record["attempts"]), "attempts_planned": 24, "period": period}))
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
            if settings_match and candidate["quality"]["usable"]:
                if all(isinstance(candidate.get("metadata", {}).get(symbol), dict) and "fields" in candidate["metadata"][symbol] for symbol in spec.symbols):
                    cached = path.parent
                    break
        data_directory = cached or directory / "dataset"
        frames, manifest = load_daily(cached) if cached else acquire_daily_observations(spec, data_directory, ticker_factory=ticker_factory)
        record.update(source=manifest["source"], dataset_id=manifest["dataset_id"], data_quality=manifest["quality"],
                      provenance_ref=str(data_directory.relative_to(root) / "manifest.json"),
                      data_acquisition="Exact checksummed snapshot reused with original retrieval date" if cached else "New explicit development-only acquisition")
        atomic_text(output / "data-manifest.json", canonical(manifest))
        xlf = frames["XLF"].copy()
        local_dates = xlf.index.tz_convert("America/New_York") if xlf.index.tz is not None else xlf.index
        mask = (local_dates.date >= date(2016, 9, 15)) & (local_dates.date <= date(2016, 9, 23))
        record["known_action_review"] = {"event": "2016-09-19 XLF distribution of XLRE shares; provider-adjusted proxy requires independent confirmation",
            "rows": frame_record(xlf.loc[mask]), "status": "unresolved_for_operational_accounting"}
        benchmarks = [SectorPolicySpec(kind="sector_equal_weight"), SectorPolicySpec(kind="buy_hold")]
        # Training and sensitivity are reported, never used to replace the declared primary.
        for policy in benchmarks + grid:
            attempt(policy, "training_benchmark" if policy.kind != "sector_momentum" else "training", spec.development_start, "2013-01-01", 5.0)
        configurations = set()
        for (text,) in database.execute("SELECT protocol FROM studies"):
            prior = json.loads(text)
            if "candidate_grid" in prior:
                configurations.update((prior["protocol_id"], canonical(policy)) for policy in prior["candidate_grid"])
            elif "lookbacks" in prior.get("protocol", {}):
                configurations.update((prior["protocol_id"], kind, lookback) for kind in ["sma_cash", "relative_momentum"] for lookback in prior["protocol"]["lookbacks"])
        search_count = max(10, len(configurations))
        for cost in spec.cost_bps:
            references = {policy.kind: attempt(policy, "validation_benchmark", spec.validation_start, spec.development_end, cost)[1] for policy in benchmarks}
            for policy in grid:
                item, result = attempt(policy, "validation", spec.validation_start, spec.development_end, cost)
                for kind, benchmark in references.items():
                    record["comparisons"].append({"attempt_id": item["attempt_id"], "policy": policy.model_dump(), "primary": policy.model_dump() == protocol["primary"],
                        "cost_bps": cost, "metrics": result["metrics"], "benchmark": kind, "benchmark_metrics": benchmark["metrics"],
                        "excess_cagr_percentage_points": result["metrics"]["cagr_pct"] - benchmark["metrics"]["cagr_pct"],
                        "evidence": paired_evidence(result, benchmark, configurations=search_count)})
                save()
        primary = [item for item in record["comparisons"] if item["primary"]]
        outcomes = [item["evidence"]["assessment"] for item in primary]
        record["assessment"] = "promising_requires_replication" if all(outcome == "promising_requires_replication" for outcome in outcomes) else "rejects_alpha_claim" if all(outcome == "rejects_alpha_claim" for outcome in outcomes) else "inconclusive"
        record["assessment_reason"] = "Declared primary is compared with both passive references across costs; positive profit alone is insufficient. Known corporate-action and execution limitations block promotion."
        record["multiple_testing"] = {"sector_configurations": 4, "known_prior_configurations": 6, "local_protocol_configuration_pairs": len(configurations),
            "correction_configurations": search_count, "warning": "Benchmarks/cost views overlap; resampling assumptions and unknown external searches preclude a calibrated edge probability"}
        record["metrics"] = {"attempts": len(record["attempts"]), "primary_validation_results": [{"policy": item["policy"], "cost_bps": item["cost_bps"],
            "benchmark": item["benchmark"], "cagr_pct": item["metrics"]["cagr_pct"], "benchmark_cagr_pct": item["benchmark_metrics"]["cagr_pct"],
            "max_drawdown_pct": item["metrics"].get("max_drawdown_pct"), "total_cost": item["metrics"].get("total_cost"),
            "excess_cagr_percentage_points": item["excess_cagr_percentage_points"], "assessment": item["evidence"]["assessment"]} for item in primary]}
        record["status"] = "complete"
        from .sector_reporting import write_sector_report
        write_sector_report(record, directory, output)
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
    spec = SectorResearchSpec.model_validate(json.loads(args.request.read_text(encoding="utf-8"))["sector_research"])
    record = run_sector_research(spec, args.root, args.output, args.experiment_id)
    print(canonical({key: record[key] for key in ["experiment_id", "status", "assessment", "metrics", "errors"]}))
    return 0 if record["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
