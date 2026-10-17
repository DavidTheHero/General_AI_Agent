"""Real-data feasibility studies for daily ETF hypotheses; no operational trading."""
import argparse
from datetime import date, timedelta
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import Field, model_validator
import yfinance as yf

from .calendar import MarketCalendar
from .config import Settings
from .data import DataError, snapshot_history_metadata
from .datasets import canonical, checksum, frame_record, record_frame, utcnow
from .reporting import atomic_text


class DailyResearchSpec(Settings):
    source: Literal["yahoo"] = "yahoo"
    symbols: list[str] = Field(default_factory=lambda: ["SPY", "IEF", "GLD"], min_length=3, max_length=3)
    data_start: str = "2005-01-03"
    development_start: str = "2006-01-03"
    validation_start: str = "2013-01-02"
    development_end: str = "2022-12-30"
    reserved_final_start: str = "2023-01-03"
    reserved_final_end: str = "2025-12-31"
    initial_cash: float = Field(default=100000, gt=0, le=1e12)
    cost_bps: list[float] = Field(default_factory=lambda: [5.0, 10.0, 20.0], min_length=1, max_length=3)
    lookbacks: list[int] = Field(default_factory=lambda: [126, 189, 252], min_length=1, max_length=3)

    @model_validator(mode="after")
    def valid_study(self):
        if self.symbols != ["SPY", "IEF", "GLD"]:
            raise ValueError("The first pilot freezes the universe/order to SPY, IEF, GLD; a new universe requires a separate hypothesis")
        dates = [self.data_start, self.development_start, self.validation_start, self.development_end, self.reserved_final_start, self.reserved_final_end]
        for value in dates:
            if date.fromisoformat(value).isoformat() != value:
                raise ValueError("Use exact ISO dates")
        if dates != sorted(set(dates)):
            raise ValueError("Require data start < training start < validation start < development end < reserved final start < final end")
        if (date.fromisoformat(self.development_start) - date.fromisoformat(self.data_start)).days < 365:
            raise ValueError("Reserve at least a calendar year for pre-study warm-up observations")
        if not 365 <= (date.fromisoformat(self.development_end) - date.fromisoformat(self.validation_start)).days <= 7305:
            raise ValueError("Validation must span 1–20 years")
        if (date.fromisoformat(self.development_end) - date.fromisoformat(self.data_start)).days > 10958:
            raise ValueError("Acquisition is bounded to 30 calendar years")
        if self.lookbacks != sorted(set(self.lookbacks)) or any(type(value) is not int or not 63 <= value <= 252 for value in self.lookbacks):
            raise ValueError("Use 1–3 sorted distinct lookbacks in 63–252 sessions")
        if self.cost_bps != sorted(set(self.cost_bps)) or any(not math.isfinite(value) or not 0 <= value <= 100 for value in self.cost_bps):
            raise ValueError("Use 1–3 sorted distinct transaction-cost scenarios in 0–100 bps per traded dollar")
        return self


def acquire_daily(spec, directory, *, ticker_factory=yf.Ticker, calendar=None):
    """No final-period requests. Archive the adapter response before validation."""
    spec = DailyResearchSpec.model_validate(spec)
    return acquire_daily_observations(spec, directory, ticker_factory=ticker_factory, calendar=calendar)


def acquire_daily_observations(spec, directory, *, ticker_factory=yf.Ticker, calendar=None):
    """Shared capture for explicitly validated daily study protocols."""
    from .daily_screen import validate_daily_frames
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    end_exclusive = (date.fromisoformat(spec.development_end) + timedelta(days=1)).isoformat()
    request = {"symbols": spec.symbols, "start": spec.data_start, "end_exclusive": end_exclusive, "interval": "1d",
               "auto_adjust": False, "back_adjust": False, "actions": True, "repair": False, "keepna": True,
               "prepost": False, "rounding": False}
    atomic_text(directory / "request.json", canonical(request))
    frames, metadata = {}, {}
    try:
        calendar = calendar or MarketCalendar()
        sessions = calendar.sessions(spec.data_start, spec.development_end)
        if not sessions or sessions[-1].close > pd.Timestamp.now(tz="UTC"):
            raise DataError("Daily research requires completed historical sessions")
        for symbol in spec.symbols:
            ticker = ticker_factory(symbol)
            frame, details, error_text = None, {}, None
            try:
                frame = ticker.history(start=spec.data_start, end=end_exclusive, interval="1d", auto_adjust=False,
                    back_adjust=False, actions=True, repair=False, keepna=True, prepost=False, rounding=False, timeout=15, raise_errors=True)
                provider_metadata = ticker.get_history_metadata() or {}
                details = snapshot_history_metadata(provider_metadata)
            except Exception as error:
                error_text = str(error)
            path = directory / f"raw-{symbol}.json"
            with path.open("x") as stream:
                stream.write(canonical({"symbol": symbol, "request": request, "retrieved_at": utcnow(), "metadata": details,
                                        "frame": frame_record(frame) if frame is not None else None, "error": error_text}))
                stream.flush()
                os.fsync(stream.fileno())
            path.chmod(0o444)
            if error_text:
                raise DataError(f"{symbol}: Yahoo daily acquisition failed: {error_text}")
            fields = details["fields"]
            if fields.get("currency") != "USD":
                raise DataError(f"{symbol}: expected USD metadata, received {fields.get('currency')!r}")
            if fields.get("exchangeTimezoneName") != "America/New_York":
                raise DataError(f"{symbol}: unsupported or unavailable session timezone")
            frames[symbol], metadata[symbol] = frame, details
        quality = validate_daily_frames(frames, [session.date for session in sessions])
        quality["corporate_actions"] = {symbol: {column: {"count": int((frame[column].fillna(0) != 0).sum()),
            "first_event": frame.index[frame[column].fillna(0) != 0][0].isoformat() if (frame[column].fillna(0) != 0).any() else None}
            for column in ["Dividends", "Capital Gains", "Stock Splits"] if column in frame} for symbol, frame in frames.items()}
        manifest = {"schema_version": "daily-proxy-1.0.0", "source": "Yahoo Finance via yfinance", "created_at": utcnow(),
                    "request": request, "observation_type": "daily_aggregated_ohlcv_and_revised_adjusted_close", "metadata": metadata,
                    "quality": quality, "files": {path.name: checksum(path) for path in sorted(directory.iterdir())},
                    "final_period_requested": False,
                    "limitations": ["Adapter DataFrames, not original Yahoo wire bytes", "Adjusted OHLC are normalized total-return research units, not executable share prices",
                                    "Fixed surviving ETF universe chosen retrospectively; no point-in-time universe or revision history",
                                    "No independent-provider validation or measured historical spreads"]}
        manifest["dataset_id"] = hashlib.sha256(canonical(manifest).encode()).hexdigest()
        atomic_text(directory / "manifest.json", canonical(manifest))
        for path in directory.iterdir():
            path.chmod(0o444)
        if not quality["usable"]:
            raise DataError("Daily data quality failed: " + "; ".join(quality["errors"]))
        return frames, manifest
    except (Exception, KeyboardInterrupt) as error:
        atomic_text(directory / "failure.json", canonical({"error": str(error) or type(error).__name__, "timestamp": utcnow(),
            "responses": [{"file": path.name, "sha256": checksum(path)} for path in directory.glob("raw-*.json")]}))
        raise


def load_daily(directory):
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text())
    core = {key: value for key, value in manifest.items() if key != "dataset_id"}
    if hashlib.sha256(canonical(core).encode()).hexdigest() != manifest["dataset_id"]:
        raise DataError("Daily manifest checksum mismatch")
    for name, expected in manifest["files"].items():
        if Path(name).name != name or checksum(directory / name) != expected:
            raise DataError(f"Daily checksum mismatch: {name}")
    if not manifest["quality"]["usable"]:
        raise DataError("Daily dataset is not usable")
    frames = {symbol: record_frame(json.loads((directory / f"raw-{symbol}.json").read_text())["frame"]) for symbol in manifest["request"]["symbols"]}
    return frames, manifest


def _monthly_returns(rows, initial_cash):
    values = pd.Series([row["equity"] for row in rows], index=pd.to_datetime([row["date"] for row in rows]))
    ends = values.groupby(values.index.to_period("M")).last()
    previous = ends.shift(1)
    previous.iloc[0] = initial_cash
    return np.log(ends / previous).to_numpy()


def paired_evidence(candidate, benchmark, *, configurations, seed=20261015):
    """Paired moving-block bootstrap; selection/dependence assumptions disclosed."""
    if [row["date"] for row in candidate["rows"]] != [row["date"] for row in benchmark["rows"]]:
        raise ValueError("Paired evidence requires identical chronological observation dates")
    candidate_months = _monthly_returns(candidate["rows"], candidate["metrics"]["initial_equity"])
    benchmark_months = _monthly_returns(benchmark["rows"], benchmark["metrics"]["initial_equity"])
    excess = candidate_months - benchmark_months
    n = len(excess)
    if n < 24:
        return {"months": n, "assessment": "inconclusive", "reason": "Fewer than 24 monthly observations", "lower_annualized_log_excess": None, "upper_annualized_log_excess": None}
    rng = np.random.default_rng(seed)
    block = min(12, n)
    means = []
    for _ in range(5000):
        starts = rng.integers(0, n - block + 1, size=math.ceil(n / block))
        sample = np.concatenate([excess[start:start + block] for start in starts])[:n]
        means.append(float(sample.mean() * 12))
    alpha = 0.05 / max(configurations, 1)
    lower, upper = np.quantile(means, [alpha / 2, 1 - alpha / 2])
    estimate = float(excess.mean() * 12)
    months = pd.PeriodIndex(pd.to_datetime([row["date"] for row in candidate["rows"]]), freq="M").unique()
    subperiods = []
    for first_year in range(months[0].year, months[-1].year + 1, 2):
        selected = (months.year >= first_year) & (months.year < first_year + 2)
        subperiods.append({"first_year": first_year, "last_year": min(first_year + 1, months[-1].year),
                          "candidate_return_pct": float(np.expm1(candidate_months[selected].sum()) * 100),
                          "benchmark_return_pct": float(np.expm1(benchmark_months[selected].sum()) * 100),
                          "log_excess_pct": float(excess[selected].sum() * 100)})
    return {"months": n, "annualized_log_excess": estimate, "lower_annualized_log_excess": float(lower),
            "upper_annualized_log_excess": float(upper), "block_months": block, "bootstrap_draws": 5000,
            "family_configurations": configurations, "validation_subperiods": subperiods,
            "assessment": "promising_requires_replication" if lower > 0 else "rejects_alpha_claim" if upper < 0 else "inconclusive",
            "limitations": "Historical paired monthly log-return difference, not factor alpha. Block/bootstrap stationarity and multiplicity assumptions can fail. Does not remove retrospective universe or human research selection."}


def run_daily_research(spec, root, output, experiment_id, *, ticker_factory=yf.Ticker):
    from .daily_screen import DailyPolicySpec, reconcile_daily_proxy, simulate_daily
    from .research import _environment
    spec = DailyResearchSpec.model_validate(spec)
    root, output = Path(root), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    directory = root / "daily-studies" / experiment_id
    directory.mkdir(parents=True, exist_ok=False)
    source_directory = directory / "source"
    source_directory.mkdir()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        captured = source_directory / path.name
        captured.write_bytes(path.read_bytes())
        captured.chmod(0o444)
    protocol_id = hashlib.sha256(canonical(spec.model_dump()).encode()).hexdigest()
    record = {"schema_version": "daily-study-1.0.0", "experiment_id": experiment_id, "protocol_id": protocol_id,
              "status": "running", "generated_at": utcnow(), "source": "Yahoo daily acquisition pending", "metrics": {}, "errors": [],
              "assessment": "inconclusive", "promotion_status": "research_only", "attempts": [], "protocol": spec.model_dump(), "environment": _environment(),
              "accounting": "Normalized fractional total-return proxy units; next-session adjusted open; overnight positions; zero-yield cash; no operational share fills",
              "reserved_final": {"start": spec.reserved_final_start, "end": spec.reserved_final_end, "accessed": False},
              "promotion_blockers": ["Research proxy has no raw-share corporate-action/pay-date ledger", "No independent source replication", "No reserved final evaluation", "No genuinely forward paper observations"],
              "selection_rule": "Within each family select highest training-period net excess CAGR against its preregistered benchmark; ties keep declared lookback order. Freeze before any validation metrics. All other validation configurations are sensitivity evidence, not reselection.",
              "hypotheses": {"sma_cash": "Persistent repricing may make a monthly long/cash SPY trend rule useful; whipsaws and missed rebounds can erase it",
                             "relative_momentum": "Persistent relative demand across equities, Treasuries and gold may make monthly positive-momentum allocation useful; regime reversals and exposures can explain apparent profits"}}
    record["source_snapshot"] = {path.name: checksum(path) for path in source_directory.iterdir()}
    if record["source_snapshot"] != record["environment"]["source_sha256"]:
        raise ValueError("Source changed while taking the research snapshot; create a new study")
    database = sqlite3.connect(root / "daily-studies.sqlite", timeout=30)
    database.execute("CREATE TABLE IF NOT EXISTS reservations (universe TEXT PRIMARY KEY, start TEXT, end TEXT)")
    database.execute("CREATE TABLE IF NOT EXISTS studies (id TEXT PRIMARY KEY, protocol TEXT, status TEXT)")
    database.execute("INSERT INTO studies VALUES (?,?,?)", (experiment_id, canonical(record), "running"))
    database.commit()

    def save():
        record["generated_at"] = utcnow()
        atomic_text(directory / "daily-study.json", canonical(record))
        atomic_text(output / "daily-study.json", canonical(record))
        atomic_text(output / "summary.json", canonical({key: record[key] for key in ["status", "generated_at", "source", "metrics", "errors", "experiment_id", "protocol_id", "assessment", "promotion_status"]} | {"provenance_ref": record.get("provenance_ref")}))
        database.execute("UPDATE studies SET status=?, protocol=? WHERE id=?", (record["status"], canonical(record), experiment_id))
        database.commit()

    def evaluate(policy, period, start, end, cost):
        attempt_id = f"{experiment_id}-{len(record['attempts']) + 1:04}"
        item = {"attempt_id": attempt_id, "policy": policy.model_dump(), "period": period, "start": start, "end": end,
                "cost_bps": cost, "status": "running", "metrics": {}, "artifact_ref": f"daily-studies/{experiment_id}/{attempt_id}.json"}
        record["attempts"].append(item)
        with (directory / "attempts.jsonl").open("a") as stream:
            stream.write(canonical({"event": "started", **item}) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        save()
        result = simulate_daily(frames, policy, start, end, cost_bps=cost, initial_cash=spec.initial_cash)
        reconciliation = reconcile_daily_proxy(result, frames)
        if not reconciliation["ok"]:
            raise ValueError("Independent daily proxy reconciliation failed: " + "; ".join(reconciliation["errors"]))
        item.update(status="complete", metrics=result["metrics"], reconciliation=reconciliation)
        atomic_text(directory / f"{attempt_id}.json", canonical({"attempt": item, "result": result}))
        with (directory / "attempts.jsonl").open("a") as stream:
            stream.write(canonical({"event": "completed", **item}) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        atomic_text(output / "progress.json", canonical({"state": "daily_research", "attempt_id": attempt_id, "attempts_completed": len(record["attempts"]), "period": period}))
        save()
        return item, result

    save()
    try:
        with database:
            universe = canonical(spec.symbols)
            database.execute("INSERT OR IGNORE INTO reservations VALUES (?,?,?)", (universe, spec.reserved_final_start, spec.reserved_final_end))
            reserved = database.execute("SELECT start,end FROM reservations WHERE universe=?", (universe,)).fetchone()
            if tuple(reserved) != (spec.reserved_final_start, spec.reserved_final_end) or spec.development_end >= reserved[0]:
                raise ValueError("This universe already reserves a different final period; no development request may access it")
        atomic_text(directory / "preregistered.json", canonical(record))
        expected_request = {"symbols": spec.symbols, "start": spec.data_start,
                            "end_exclusive": (date.fromisoformat(spec.development_end) + timedelta(days=1)).isoformat()}
        cached = None
        for path in sorted((root / "daily-studies").glob("*/dataset/manifest.json")):
            candidate = json.loads(path.read_text())
            structured_metadata = all(isinstance(candidate.get("metadata", {}).get(symbol), dict) and "fields" in candidate["metadata"][symbol] for symbol in spec.symbols)
            if structured_metadata and candidate["quality"]["usable"] and all(candidate["request"].get(key) == value for key, value in expected_request.items()):
                cached = path.parent
                break
        if cached:
            frames, manifest = load_daily(cached)
            data_directory = cached
            record["data_acquisition"] = "Reused the exact checksummed development snapshot; retrieval time remains the original manifest time"
        else:
            frames, manifest = acquire_daily(spec, directory / "dataset", ticker_factory=ticker_factory)
            data_directory = directory / "dataset"
            record["data_acquisition"] = "New explicit Yahoo request; original adapter responses archived before checks"
        record.update(source=manifest["source"], dataset_id=manifest["dataset_id"], data_quality=manifest["quality"],
                      provenance_ref=str(data_directory.relative_to(root) / "manifest.json"))
        atomic_text(output / "data-manifest.json", canonical(manifest))
        training_end = (date.fromisoformat(spec.validation_start) - timedelta(days=1)).isoformat()
        base_cost = spec.cost_bps[0]
        benchmarks = {"sma_cash": DailyPolicySpec(kind="buy_hold"), "relative_momentum": DailyPolicySpec(kind="equal_weight")}
        training_benchmarks = {kind: evaluate(policy, "training_benchmark", spec.development_start, training_end, base_cost)[1] for kind, policy in benchmarks.items()}
        selected = {}
        for kind in benchmarks:
            choices = []
            for lookback in spec.lookbacks:
                policy = DailyPolicySpec(kind=kind, lookback=lookback)
                item, result = evaluate(policy, "training", spec.development_start, training_end, base_cost)
                excess = result["metrics"]["cagr_pct"] - training_benchmarks[kind]["metrics"]["cagr_pct"]
                choices.append((excess, policy))
            selected[kind] = max(choices, key=lambda pair: pair[0])[1].model_dump()
        record["selected_by_training"] = selected
        save()  # Selection is persisted before validation starts.
        comparisons = []
        local_configurations = set()
        for (previous,) in database.execute("SELECT protocol FROM studies"):
            prior = json.loads(previous)
            if prior["protocol"]["symbols"] == spec.symbols:
                for lookback in prior["protocol"]["lookbacks"]:
                    for kind in benchmarks:
                        local_configurations.add((prior["protocol_id"], kind, lookback))
        configurations = len(local_configurations)
        for cost in spec.cost_bps:
            validation_benchmarks = {kind: evaluate(policy, "validation_benchmark", spec.validation_start, spec.development_end, cost)[1] for kind, policy in benchmarks.items()}
            for kind in benchmarks:
                for lookback in spec.lookbacks:
                    policy = DailyPolicySpec(kind=kind, lookback=lookback)
                    item, result = evaluate(policy, "validation", spec.validation_start, spec.development_end, cost)
                    evidence = paired_evidence(result, validation_benchmarks[kind], configurations=configurations)
                    comparisons.append({"attempt_id": item["attempt_id"], "policy": policy.model_dump(), "cost_bps": cost,
                        "selected_by_training": policy.model_dump() == selected[kind], "metrics": result["metrics"],
                        "benchmark": benchmarks[kind].kind, "benchmark_metrics": validation_benchmarks[kind]["metrics"],
                        "excess_cagr_percentage_points": result["metrics"]["cagr_pct"] - validation_benchmarks[kind]["metrics"]["cagr_pct"], "evidence": evidence})
                    record["comparisons"] = comparisons
                    save()
        chosen = [item for item in comparisons if item["selected_by_training"]]
        record["assessment"] = "promising_requires_replication" if all(item["evidence"]["assessment"] == "promising_requires_replication" for item in chosen) else "rejects_alpha_claim" if all(item["evidence"]["assessment"] == "rejects_alpha_claim" for item in chosen) else "inconclusive"
        record["assessment_reason"] = "Positive strategy profit alone does not establish incremental value. Inspect paired excess estimates, uncertainty, benchmarks and stressed costs. Final period remains untouched; promotion is blocked."
        record["multiple_testing"] = {"declared_candidate_configurations": 2 * len(spec.lookbacks), "local_protocol_configurations": configurations, "recorded_attempts": len(record["attempts"]),
            "bootstrap": "12-month moving blocks, 5000 draws, Bonferroni across distinct locally declared protocol/configuration pairs; assumptions remain approximate and external searches are unknown"}
        record["status"] = "complete"
        record["metrics"] = {"attempts": len(record["attempts"]), "validation_years": (date.fromisoformat(spec.development_end) - date.fromisoformat(spec.validation_start)).days / 365.25,
                             "selected_validation_results": [{"policy": item["policy"], "cost_bps": item["cost_bps"], "cagr_pct": item["metrics"]["cagr_pct"],
                             "excess_cagr_percentage_points": item["excess_cagr_percentage_points"], "assessment": item["evidence"]["assessment"]} for item in chosen]}
        from .daily_reporting import write_daily_report
        write_daily_report(record, directory, output)
    except (Exception, KeyboardInterrupt) as error:
        record["status"] = "cancelled" if isinstance(error, KeyboardInterrupt) else "failed"
        record["errors"].append(str(error) or type(error).__name__)
        for item in record["attempts"]:
            if item["status"] == "running":
                item.update(status=record["status"], error=str(error) or type(error).__name__, artifact_available=False)
                with (directory / "attempts.jsonl").open("a") as stream:
                    stream.write(canonical({"event": "terminated", **item}) + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
    finally:
        try:
            save()
        finally:
            database.close()
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--runtime-worker", action="store_true")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[a-f0-9]{32}", args.experiment_id):
        parser.error("experiment-id must be 32 hexadecimal characters")
    from .worker_control import install_worker_control
    install_worker_control(args.runtime_worker)
    value = json.loads(args.request.read_text(encoding="utf-8"))
    spec = DailyResearchSpec.model_validate(value["daily_research"])
    result = run_daily_research(spec, args.root, args.output, args.experiment_id)
    print(canonical({key: result.get(key) for key in ["experiment_id", "status", "assessment", "promotion_status", "errors", "metrics"]}))
    return 0 if result["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
