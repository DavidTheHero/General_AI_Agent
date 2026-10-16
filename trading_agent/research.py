"""Bounded reproducible studies. Runtime workers, never MCP connections, own work."""
import argparse
from datetime import date
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import signal
import sqlite3
import sys
import threading
from typing import Literal
import importlib.metadata

from pydantic import Field, model_validator

from .calendar import MarketCalendar
from .config import AgentConfig, Settings, StrategyConfig
from .data import session_frames
from .datasets import DatasetStore, canonical, checksum, utcnow
from .engine import IntradayAgent
from .metrics import equity_curve, performance_metrics
from .reconciliation import reconcile_session
from .reporting import atomic_text
from .daily_research import DailyResearchSpec
from .sector_research import SectorResearchSpec
from .weekly_research import WeeklyResearchSpec


class DatasetRequest(Settings):
    source: Literal["synthetic", "yahoo"] = "synthetic"
    symbols: list[str] = Field(default_factory=lambda: ["SPY", "AAPL"], min_length=1, max_length=10)
    start: str
    end: str
    interval: Literal["1m", "2m", "5m", "15m", "30m", "60m"] = "5m"
    seed: int = Field(default=7, ge=0, le=2**32 - 1)

    @model_validator(mode="after")
    def valid_request(self):
        for value in [self.start, self.end]:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                raise ValueError("Dataset dates must be YYYY-MM-DD")
            date.fromisoformat(value)
        if not 0 <= (date.fromisoformat(self.end) - date.fromisoformat(self.start)).days <= 370:
            raise ValueError("Dataset range must be ordered and at most 370 calendar days")
        validated = AgentConfig(symbols=self.symbols, interval=self.interval)
        if self.symbols != validated.symbols:
            raise ValueError("Use normalized uppercase symbols without surrounding whitespace")
        return self


class ExperimentSpec(Settings):
    dataset_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    config: AgentConfig = Field(default_factory=AgentConfig)
    candidates: list[StrategyConfig] = Field(min_length=1, max_length=12)
    train_sessions: int = Field(default=3, ge=2, le=200)
    validation_sessions: int = Field(default=2, ge=1, le=60)
    final_sessions: int = Field(default=2, ge=2, le=60)
    cost_multipliers: list[float] = Field(default_factory=lambda: [1.0, 2.0], min_length=2, max_length=3)
    finalize: bool = False
    parent_experiment_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")

    @model_validator(mode="after")
    def valid_protocol(self):
        if len({canonical(item.model_dump()) for item in self.candidates}) != len(self.candidates):
            raise ValueError("Candidate configurations must be distinct")
        if sorted(set(self.cost_multipliers)) != self.cost_multipliers or self.cost_multipliers[0] != 1 or any(not math.isfinite(value) or not 1 <= value <= 5 for value in self.cost_multipliers):
            raise ValueError("Use sorted distinct cost multipliers beginning with 1 and at least one stress scenario, maximum 5")
        if self.finalize != (self.parent_experiment_id is not None):
            raise ValueError("Final evaluation requires parent_experiment_id; validation must omit it")
        # Reject an impossible stress protocol before any work is submitted.
        for multiplier in self.cost_multipliers:
            type(self.config.costs).model_validate({key: value * multiplier for key, value in self.config.costs.model_dump().items()})
        return self

    def protocol(self):
        return self.model_dump(exclude={"finalize", "parent_experiment_id"})


class ResearchJobRequest(Settings):
    mode: Literal["dataset", "experiment", "daily_research", "sector_research", "weekly_research"]
    dataset: DatasetRequest | None = None
    experiment: ExperimentSpec | None = None
    daily_research: DailyResearchSpec | None = None
    sector_research: SectorResearchSpec | None = None
    weekly_research: WeeklyResearchSpec | None = None

    @model_validator(mode="after")
    def matching_payload(self):
        for mode in ["dataset", "experiment", "daily_research", "sector_research", "weekly_research"]:
            if (getattr(self, mode) is not None) != (self.mode == mode):
                raise ValueError(f"{self.mode} mode requires only {self.mode}")
        return self


def _experiment_dir(root, experiment_id):
    if not re.fullmatch(r"[a-f0-9]{32}", experiment_id):
        raise ValueError("Use an exact experiment_id")
    return Path(root) / "experiments" / experiment_id


def inspect_experiment(root, experiment_id):
    path = _experiment_dir(root, experiment_id) / "experiment.json"
    if not path.is_file():
        raise KeyError("Experiment has no saved research snapshot yet")
    record = json.loads(path.read_text())
    # Curves/decisions/fills remain full in per-attempt artifacts, never in MCP payloads.
    return record


def reconcile_interrupted(root, experiment_ids):
    """Terminate abandoned research metadata without replaying portfolio events."""
    root = Path(root)
    database_path = root / "research.sqlite"
    database = sqlite3.connect(database_path, timeout=30) if database_path.is_file() else None
    notice = "Runtime restarted during research. Observations after the last saved snapshot are uncertain; inspect saved progress and ledgers. This experiment is not resumed."
    reconciled = {}
    try:
        for experiment_id in experiment_ids:
            directory = _experiment_dir(root, experiment_id)
            path = directory / "experiment.json"
            record = json.loads(path.read_text()) if path.is_file() else None
            events_path = directory / "attempts.jsonl"
            events = [json.loads(line) for line in events_path.read_text().splitlines()] if events_path.is_file() else []
            recorded_interruptions = {event["attempt_id"] for event in events if event["event"] == "restart_reconciled"}
            attempts = {item["attempt_id"]: item for item in record.get("attempts", [])} if record else {}
            abandoned_attempts = set()
            if database:
                for attempt_id, configuration, result in database.execute(
                        "SELECT id, configuration, result FROM attempts WHERE experiment_id=? AND status='running'", (experiment_id,)):
                    abandoned_attempts.add(attempt_id)
                    if attempt_id not in attempts:
                        attempts[attempt_id] = json.loads(result or configuration)
            for attempt_id, item in attempts.items():
                if item.get("status") != "running" and attempt_id not in abandoned_attempts:
                    continue
                append_event = item.get("status") != "interrupted"
                item.update(status="interrupted", error=notice)
                # Retain the reference even if a worker died before producing it;
                # availability is explicit and the last progress snapshot is untouched.
                item["artifact_available"] = bool(re.fullmatch(re.escape(experiment_id) + r"-\d{4}", attempt_id)
                                                  and (directory / f"{attempt_id}.json").is_file())
                if database:
                    database.execute("UPDATE attempts SET status='interrupted', result=? WHERE id=? AND experiment_id=?",
                                     (canonical(item), attempt_id, experiment_id))
                if append_event and attempt_id not in recorded_interruptions:
                    with events_path.open("a") as stream:
                        stream.write(canonical({"event": "restart_reconciled", "reconciled_at": utcnow(), **item}) + "\n")
                        stream.flush()
                        os.fsync(stream.fileno())
            if record:
                record["status"] = "interrupted"
                record["generated_at"] = utcnow()
                record["attempts"] = list(attempts.values())
                if notice not in record.setdefault("errors", []):
                    record["errors"].append(notice)
                atomic_text(path, canonical(record))
                reconciled[experiment_id] = record
        if database:
            database.commit()
    finally:
        if database:
            database.close()
    return reconciled


def inspect_attempt(root, experiment_id, attempt_id):
    directory = _experiment_dir(root, experiment_id)
    if not re.fullmatch(re.escape(experiment_id) + r"-\d{4}", attempt_id):
        raise ValueError("Use an exact attempt_id belonging to this experiment")
    path = directory / f"{attempt_id}.json"
    if not path.is_file():
        raise KeyError("Attempt evidence is not available yet")
    evidence = json.loads(path.read_text())
    sessions = []
    for session in evidence["sessions"][-3:]:
        sessions.append({**{key: session.get(key) for key in ["session", "status", "finished", "valuation_timestamp", "holdings"]},
                         "equity": equity_curve([session])[-100:], "fills": session["fills"][-100:],
                         "decisions": [{key: value for key, value in decision.items() if key != "policy_audit"} for decision in session["decisions"][-50:]],
                         "events": session["events"][-20:]})
    return {"experiment_id": experiment_id, "attempt_id": attempt_id, "attempt": evidence["attempt"], "config": evidence["config"],
            "reconciliations": evidence["reconciliations"][-3:], "sessions": sessions,
            "truncated": len(evidence["sessions"]) > 3 or any(len(session["equity"]) > 100 or len(session["fills"]) > 100 or len(session["decisions"]) > 50 or len(session["events"]) > 20 for session in evidence["sessions"]),
            "artifact_ref": evidence["attempt"]["artifact_ref"]}


def list_experiments(root, limit=20):
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 50:
        raise ValueError("Experiment listing limit must be 1–50")
    directory = Path(root) / "experiments"
    if not directory.exists():
        return []
    paths = sorted(directory.glob("*/experiment.json"), key=lambda path: path.stat().st_mtime, reverse=True)[:limit]
    return [{key: record.get(key) for key in ["experiment_id", "dataset_id", "protocol_id", "status", "generated_at", "assessment", "metrics", "selected_strategy"]}
            for path in paths for record in [json.loads(path.read_text())]]


def compare_experiments(root, experiment_ids):
    if not 2 <= len(experiment_ids) <= 6 or len(set(experiment_ids)) != len(experiment_ids):
        raise ValueError("Compare 2–6 distinct experiments")
    records = [inspect_experiment(root, experiment_id) for experiment_id in experiment_ids]
    if len({(record["dataset_id"], record["protocol_id"], record["split"]["final_test_accessed"], canonical(record["environment"])) for record in records}) != 1:
        raise ValueError("Experiments are incomparable: dataset, protocol, software environment and evaluation period must match")
    return {"comparable": True, "dataset_id": records[0]["dataset_id"], "protocol_id": records[0]["protocol_id"],
            "experiments": [{key: record.get(key) for key in ["experiment_id", "status", "assessment", "selected_strategy", "metrics"]} for record in records]}


def _database(root):
    Path(root).mkdir(parents=True, exist_ok=True)
    database = sqlite3.connect(Path(root) / "research.sqlite", timeout=30)
    database.execute("CREATE TABLE IF NOT EXISTS holdouts (dataset_id TEXT PRIMARY KEY, final_dates TEXT NOT NULL, opened_by TEXT)")
    database.execute("CREATE TABLE IF NOT EXISTS experiments (id TEXT PRIMARY KEY, dataset_id TEXT, protocol_id TEXT, request TEXT, created_at TEXT)")
    database.execute("CREATE TABLE IF NOT EXISTS attempts (id TEXT PRIMARY KEY, experiment_id TEXT, configuration TEXT, status TEXT, result TEXT)")
    database.execute("CREATE TABLE IF NOT EXISTS dataset_aliases (dataset_id TEXT PRIMARY KEY, observation_key TEXT NOT NULL)")
    database.commit()
    return database


def _environment():
    versions = {}
    for name in ["numpy", "pandas", "pydantic", "yfinance", "exchange-calendars"]:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "unavailable"
    return {"python": platform.python_version(), "platform": platform.platform(), "packages": versions,
            "source_sha256": {path.name: checksum(path) for path in sorted(Path(__file__).parent.glob("*.py"))}}


def _folds(dates, spec):
    development, final = dates[:-spec.final_sessions], dates[-spec.final_sessions:]
    if len(final) != spec.final_sessions or len(development) < spec.train_sessions + spec.validation_sessions:
        raise ValueError("Dataset is too short for initial training, a full validation fold and the reserved final period")
    folds = []
    for start in range(spec.train_sessions, len(development), spec.validation_sessions):
        validation = development[start:min(start + spec.validation_sessions, len(development))]
        folds.append({"train": development[:start], "validation": validation})
    return development, final, folds


def _run_period(data, sessions, config, *, progress):
    results, reconciliations = [], []
    cash = config.initial_cash
    try:
        for session in sessions:
            agent = IntradayAgent(config, session, cash)
            try:
                frames = session_frames(data, session, config)
                for timestamp in session.grid(config.minutes):
                    agent.observe(timestamp, {symbol: frame.loc[timestamp].to_dict() for symbol, frame in frames.items()})
                    progress(agent)
                result = agent.result()
            except BaseException:
                result = agent.result()
                results.append(result)
                reconciliations.append(reconcile_session(result, config))
                raise
            results.append(result)
            reconciliations.append(reconcile_session(result, config))
            if not reconciliations[-1]["ok"]:
                raise ValueError("Independent ledger reconciliation failed: " + "; ".join(reconciliations[-1]["errors"]))
            if not agent.finished or result["halt_reason"] == "decision_error_limit" or agent.portfolio.cash <= 0:
                raise ValueError("Period did not complete under the declared execution/policy constraints")
            cash = agent.portfolio.cash
        return results, reconciliations, None
    except BaseException as error:
        return results, reconciliations, error


def run_experiment(spec, root, output, experiment_id, *, calendar=None):
    """Persist protocol and every attempt before executing. No hidden optimization."""
    spec = ExperimentSpec.model_validate(spec)
    root, output = Path(root), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    directory = _experiment_dir(root, experiment_id)
    directory.mkdir(parents=True, exist_ok=False)
    protocol = spec.protocol()
    protocol_id = hashlib.sha256(canonical(protocol).encode()).hexdigest()
    record = {"schema_version": "1.0.0", "experiment_id": experiment_id, "protocol_id": protocol_id, "dataset_id": spec.dataset_id,
              "parent_experiment_id": spec.parent_experiment_id, "protocol": protocol, "generated_at": utcnow(), "status": "running",
              "source": "dataset inspection pending", "metrics": {}, "assessment": "inconclusive", "assessment_reason": "Research has not completed",
              "attempts": [], "errors": [], "selected_strategy": None,
              "split": {"training_sessions": [], "validation_folds": [], "final_sessions": [], "final_test_accessed": False},
              "provenance_ref": f"datasets/{spec.dataset_id}/manifest.json", "artifact_ref": f"experiments/{experiment_id}",
              "environment": _environment(), "benchmark_method": "Whole-share buy-and-hold from first eligible next open, same host caps, capital, costs and scheduled daily liquidation; cash earns zero",
              "limitations": ["Aggregated OHLCV cannot establish executable liquidity or intrabar paths", "All policies reset each session; no overnight holdings",
                              "Candidate lists are bounded sensitivity studies, not exhaustive searches", "Session returns may be dependent; sign-test bounds are descriptive, not calibrated edge evidence",
                              "LLM training contamination is unknown; temperature zero does not guarantee determinism; model tags are not verified weights digests"]}
    atomic_text(directory / "protocol.json", canonical({"protocol_id": protocol_id, "request": spec.model_dump(), "environment": record["environment"]}))
    database = _database(root)
    database.execute("INSERT INTO experiments VALUES (?,?,?,?,?)", (experiment_id, spec.dataset_id, protocol_id, canonical(spec.model_dump()), utcnow()))
    database.commit()

    def save():
        record["generated_at"] = utcnow()
        atomic_text(directory / "experiment.json", canonical(record))
        atomic_text(output / "experiment.json", canonical(record))
        atomic_text(output / "summary.json", canonical({key: value for key, value in record.items() if key not in {"environment", "attempts", "protocol"}}))

    def enrich(item, **fields):
        """Comparison annotations agree across the summary, SQL and audit artifact."""
        item.update(fields)
        path = directory / f"{item['attempt_id']}.json"
        evidence = json.loads(path.read_text())
        evidence["attempt"] = item
        atomic_text(path, canonical(evidence))
        database.execute("UPDATE attempts SET result=? WHERE id=?", (canonical(item), item["attempt_id"]))
        database.commit()
        with (directory / "attempts.jsonl").open("a") as stream:
            stream.write(canonical({"event": "annotated", **item}) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        atomic_text(output / "attempts.jsonl", (directory / "attempts.jsonl").read_text())

    def attempt(strategy, dates, period, fold, multiplier):
        number = len(record["attempts"]) + 1
        attempt_id = f"{experiment_id}-{number:04}"
        costs = spec.config.costs.model_dump()
        config = spec.config.model_copy(update={"strategy": strategy, "costs": type(spec.config.costs).model_validate({key: value * multiplier for key, value in costs.items()})})
        item = {"attempt_id": attempt_id, "strategy": strategy.model_dump(), "period": period, "fold": fold,
                "cost_multiplier": multiplier, "sessions": dates, "status": "running", "metrics": {},
                "reconciliation": None, "artifact_ref": f"experiments/{experiment_id}/{attempt_id}.json"}
        record["attempts"].append(item)
        database.execute("INSERT INTO attempts VALUES (?,?,?,?,?)", (attempt_id, experiment_id, canonical(item), "running", None))
        database.commit()
        with (directory / "attempts.jsonl").open("a") as stream:
            stream.write(canonical({"event": "started", **item}) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        save()
        latest = [None]

        def progress(agent):
            # One atomic progress write per 12 bars; cancellation still interrupts every bar.
            if len(agent.history[config.symbols[0]]) % 12 == 0 or agent.finished:
                latest[0] = agent.result()
                atomic_text(output / "progress.json", canonical({"state": "research", "experiment_id": experiment_id, "dataset_id": spec.dataset_id,
                    "attempt_id": attempt_id, "attempts_completed": number - 1, "session": agent.session.date,
                    "completed_bars": len(agent.history[config.symbols[0]]), "valuation_timestamp": latest[0]["valuation_timestamp"],
                    "holdings": latest[0]["holdings"], "equity": latest[0]["equity"][-100:], "fills": latest[0]["fills"][-20:], "decisions": latest[0]["decisions"][-10:]}))

        selected_sessions = [session_map[day] for day in dates]
        results, reconciliations, error = _run_period(data, selected_sessions, config, progress=progress)
        item["status"] = "cancelled" if isinstance(error, KeyboardInterrupt) else "failed" if error else "complete"
        item["metrics"] = performance_metrics(results, config.initial_cash)
        # The legacy chart benchmark is fractional/cost-free. Research only exposes
        # separately executed matched benchmarks, attached by enrich() below.
        item["metrics"]["benchmark_return_pct"] = None
        item["metrics"]["cash_benchmark_return_pct"] = 0.0 if not error else None
        if item["metrics"]["completed_sessions"] < 30:
            item["metrics"]["daily_sharpe_zero_risk_free"] = None
            item["metrics"]["annualized_daily_volatility_pct"] = None
            item["metrics"]["statistical_note"] = "Annualized research estimates withheld with fewer than 30 completed sessions; session returns remain available"
        item["daily_returns"] = [{"session": result["session"], "return": result["final_equity"] / result["initial_equity"] - 1} for result in results if result["finished"] and result["initial_equity"] > 0]
        item["reconciliation"] = {"ok": all(result["ok"] for result in reconciliations), "sessions_checked": len(reconciliations), "errors": [error for result in reconciliations for error in result["errors"]]}
        item["error"] = (str(error) or type(error).__name__) if error else None
        atomic_text(directory / f"{attempt_id}.json", canonical({"attempt": item, "config": config.model_dump(), "sessions": results, "reconciliations": reconciliations}))
        database.execute("UPDATE attempts SET status=?, result=? WHERE id=?", (item["status"], canonical(item), attempt_id))
        database.commit()
        with (directory / "attempts.jsonl").open("a") as stream:
            stream.write(canonical({"event": "finished", **item}) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        atomic_text(output / "attempts.jsonl", (directory / "attempts.jsonl").read_text())
        save()
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise error
        return item

    save()
    try:
        store = DatasetStore(root / "datasets")
        data, manifest = store.load(spec.dataset_id)
        observation_key = manifest.get("observation_fingerprint", spec.dataset_id)
        database.execute("INSERT OR IGNORE INTO dataset_aliases VALUES (?,?)", (spec.dataset_id, observation_key))
        database.commit()
        record["source"] = manifest["source"]
        record["data_quality"] = manifest["quality"]
        if spec.config.symbols != manifest["request"]["symbols"] or spec.config.interval != manifest["request"]["interval"]:
            raise ValueError("Experiment symbols and interval must exactly match the immutable dataset request")
        calendar = calendar or MarketCalendar()
        session_map = {session.date: session for session in calendar.sessions(manifest["request"]["start"], manifest["request"]["end"])}
        dates = manifest["sessions"]
        development, final, folds = _folds(dates, spec)
        record["split"].update(training_sessions=folds[0]["train"], validation_folds=folds, final_sessions=final)
        benchmark_count = len({candidate.target_gross_weight for candidate in spec.candidates})
        planned_attempts = 2 * len(spec.cost_multipliers) if spec.finalize else len(folds) * (len(spec.candidates) + (len(spec.candidates) + benchmark_count) * len(spec.cost_multipliers))
        evaluated_sessions = 2 * len(final) * len(spec.cost_multipliers) if spec.finalize else sum(len(fold["train"]) * len(spec.candidates) + len(fold["validation"]) * (len(spec.candidates) + benchmark_count) * len(spec.cost_multipliers) for fold in folds)
        if planned_attempts > 160 or evaluated_sessions * len(spec.config.symbols) * math.ceil(390 / spec.config.minutes) > 250000:
            raise ValueError("Experiment exceeds the 160-attempt / 250000 symbol-bar budget; explicitly reduce candidates, sessions or increase interval")
        # Reservation is dataset-wide and transactional, including across runtime processes.
        with database:
            database.execute("INSERT OR IGNORE INTO holdouts VALUES (?,?,NULL)", (observation_key, canonical(final)))
            reservation = database.execute("SELECT final_dates,opened_by FROM holdouts WHERE dataset_id=?", (observation_key,)).fetchone()
            if reservation[0] != canonical(final):
                raise ValueError("This dataset already reserves a different final period; changing the split is forbidden")
            if reservation[1]:
                raise ValueError("This dataset's final period has already been accessed; new selection or final evaluation is forbidden")
        if spec.finalize:
            parent = inspect_experiment(root, spec.parent_experiment_id)
            if parent["protocol_id"] != protocol_id or parent["environment"] != record["environment"] or parent["status"] != "complete" or parent["split"]["final_test_accessed"] or not parent["selected_strategy"]:
                raise ValueError("Final evaluation requires a completed matching validation parent with frozen selection")
            record["selected_strategy"] = parent["selected_strategy"]
            with database:
                cursor = database.execute("UPDATE holdouts SET opened_by=? WHERE dataset_id=? AND opened_by IS NULL", (experiment_id, observation_key))
                if cursor.rowcount != 1:
                    raise ValueError("Final period was concurrently accessed")
            record["split"]["final_test_accessed"] = True
            save()  # Consume once even if cancellation or failure occurs afterwards.
            selected = StrategyConfig.model_validate(record["selected_strategy"])
            for multiplier in spec.cost_multipliers:
                benchmark = attempt(StrategyConfig(kind="buy_and_hold", target_gross_weight=selected.target_gross_weight), final, "final_benchmark", 0, multiplier)
                evaluated = attempt(selected, final, "final", 0, multiplier)
                if benchmark["status"] == evaluated["status"] == "complete":
                    evaluated["metrics"]["benchmark_return_pct"] = benchmark["metrics"]["return_pct"]
                    evaluated["metrics"]["excess_return_pct"] = evaluated["metrics"]["return_pct"] - benchmark["metrics"]["return_pct"]
                    enrich(evaluated)
        else:
            fold_choices = []
            validation_scores = {canonical(candidate.model_dump()): [] for candidate in spec.candidates}
            for fold_number, fold in enumerate(folds):
                training = [attempt(candidate, fold["train"], "training", fold_number, 1.0) for candidate in spec.candidates]
                successful = [item for item in training if item["status"] == "complete" and not item["metrics"]["decision_errors"]]
                if not successful:
                    raise ValueError("No candidate completed training without policy errors")
                choice = max(successful, key=lambda item: item["metrics"]["return_pct"])["strategy"]
                fold_choices.append(choice)
                for multiplier in spec.cost_multipliers:
                    # Same gross allocation per candidate; each benchmark is cached only when identical.
                    benchmarks = {}
                    for candidate in spec.candidates:
                        gross = candidate.target_gross_weight
                        if gross not in benchmarks:
                            benchmarks[gross] = attempt(StrategyConfig(kind="buy_and_hold", target_gross_weight=gross), fold["validation"], "validation_benchmark", fold_number, multiplier)
                        evaluated = attempt(candidate, fold["validation"], "validation", fold_number, multiplier)
                        benchmark = benchmarks[gross]
                        if evaluated["status"] == benchmark["status"] == "complete":
                            evaluated["metrics"]["benchmark_return_pct"] = benchmark["metrics"]["return_pct"]
                            evaluated["metrics"]["excess_return_pct"] = evaluated["metrics"]["return_pct"] - benchmark["metrics"]["return_pct"]
                            if multiplier == 1:
                                validation_scores[canonical(candidate.model_dump())].append(evaluated["metrics"]["excess_return_pct"])
                        enrich(evaluated, selected_by_training=evaluated["strategy"] == choice)
            # Freeze final candidate using all development-only validation folds; report this selection bias.
            eligible = [candidate for candidate in spec.candidates if len(validation_scores[canonical(candidate.model_dump())]) == len(folds)]
            if not eligible:
                raise ValueError("No candidate completed every validation fold")
            if database.execute("SELECT opened_by FROM holdouts WHERE dataset_id=?", (observation_key,)).fetchone()[0]:
                raise ValueError("Final period was accessed while this validation was running; no new selection is permitted")
            record["selected_strategy"] = max(eligible, key=lambda candidate: sum(validation_scores[canonical(candidate.model_dump())])).model_dump()
            record["walk_forward_choices"] = fold_choices
            record["selection_rule"] = "Highest sum of base-cost validation excess returns; ties use declared candidate order. Each fold also records a training-only winner. Final selection uses development data only. Each fold resets shared initial capital and closes positions daily; percentage sums are sensitivity scores, not a compounded deployment return."
            record["parameter_sensitivity"] = [{"strategy": candidate.model_dump(), "validation_excess_sum_pct": sum(validation_scores[canonical(candidate.model_dump())]),
                                                  "complete_folds": len(validation_scores[canonical(candidate.model_dump())])} for candidate in spec.candidates]
        chosen = [item for item in record["attempts"] if item["strategy"] == record["selected_strategy"] and item["period"] in {"final", "validation"} and item["cost_multiplier"] == 1 and item["status"] == "complete"]
        record["metrics"] = chosen[-1]["metrics"] if spec.finalize and chosen else {"validation_excess_sum_pct": sum(item["metrics"].get("excess_return_pct", 0) for item in chosen)}
        trials = database.execute("SELECT COUNT(*) FROM attempts a JOIN experiments e ON a.experiment_id=e.id WHERE e.dataset_id IN (SELECT dataset_id FROM dataset_aliases WHERE observation_key=?)", (observation_key,)).fetchone()[0]
        record["multiple_testing"] = {"candidate_configurations": len(spec.candidates), "recorded_dataset_attempts": trials,
                                      "family_wise_sign_test_bound": None, "warning": "Search attempts are dependent; unrecorded external searches cannot be counted"}
        if spec.finalize and chosen:
            benchmark = next((item for item in record["attempts"] if item["period"] == "final_benchmark" and item["cost_multiplier"] == 1), None)
            excess = [candidate["return"] - reference["return"] for candidate, reference in zip(chosen[0]["daily_returns"], benchmark["daily_returns"])] if benchmark else []
            nonzero = [value for value in excess if abs(value) > 1e-12]
            wins = sum(value > 0 for value in nonzero)
            p_value = sum(math.comb(len(nonzero), count) for count in range(wins, len(nonzero) + 1)) / 2**len(nonzero) if nonzero else 1.0
            record["multiple_testing"].update(one_sided_sign_p=p_value, family_wise_sign_test_bound=min(1, p_value * max(trials, 1)), nonzero_sessions=len(nonzero))
        failed = [item for item in record["attempts"] if item["status"] != "complete" or item["metrics"].get("decision_errors")]
        record["status"] = "partial" if failed else "complete"
        record["assessment_reason"] = "Validation is selection evidence; the final test remains reserved" if not spec.finalize else "Final test observed; sample size, dependence, model assumptions and external search history prevent an automatic edge claim"
        if spec.finalize and not manifest["source"].startswith("SYNTHETIC") and len(final) >= 20 and all(item["metrics"].get("excess_return_pct", 1) <= 0 for item in record["attempts"] if item["period"] == "final"):
            record["assessment"], record["assessment_reason"] = "rejects", "This recorded strategy failed to outperform the cost-matched benchmark across final cost scenarios"
        if manifest["source"].startswith("SYNTHETIC"):
            record["assessment_reason"] = "Synthetic data verifies software behavior; it cannot establish an economic edge"
        if failed:
            record["errors"].append(f"{len(failed)} attempts failed or encountered policy errors; inspect the attempt ledger")
    except (Exception, KeyboardInterrupt) as error:
        record["status"] = "cancelled" if isinstance(error, KeyboardInterrupt) else "failed"
        record["errors"].append(str(error) or type(error).__name__)
        # Signals can also arrive between durable registration and the bar loop.
        # Terminalize those attempts while explicitly retaining unavailable evidence.
        for item in record["attempts"]:
            if item["status"] != "running":
                continue
            item.update(status=record["status"], error=str(error) or type(error).__name__,
                        artifact_available=(directory / f"{item['attempt_id']}.json").is_file())
            database.execute("UPDATE attempts SET status=?, result=? WHERE id=?", (item["status"], canonical(item), item["attempt_id"]))
            with (directory / "attempts.jsonl").open("a") as stream:
                stream.write(canonical({"event": "terminated_before_evidence", **item}) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        database.commit()
        if (directory / "attempts.jsonl").is_file():
            atomic_text(output / "attempts.jsonl", (directory / "attempts.jsonl").read_text())
    finally:
        save()
        database.close()
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description="Immutable datasets and simulated strategy research")
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--runtime-worker", action="store_true")
    args = parser.parse_args(argv)

    def interrupt(_signal, _frame):
        raise KeyboardInterrupt()

    signal.signal(signal.SIGTERM, interrupt)
    if args.runtime_worker:
        def lifetime():
            while os.read(sys.stdin.fileno(), 1):
                pass
            os.kill(os.getpid(), signal.SIGTERM)
        threading.Thread(target=lifetime, daemon=True).start()
    args.output.mkdir(parents=True, exist_ok=True)
    try:
        request = ResearchJobRequest.model_validate_json(args.request.read_text())
        if request.mode == "experiment":
            result = run_experiment(request.experiment, args.root, args.output, args.experiment_id)
        else:
            manifest = DatasetStore(args.root / "datasets").acquire(request.dataset.model_dump())
            result = {"status": "complete" if manifest["quality"]["usable"] else "failed", "generated_at": utcnow(),
                      "source": manifest["source"], "dataset_id": manifest["dataset_id"], "metrics": {}, "errors": manifest["quality"]["errors"],
                      "provenance_ref": f"datasets/{manifest['dataset_id']}/manifest.json", "data_quality": manifest["quality"]}
        atomic_text(args.output / "summary.json", canonical(result))
        return 0 if result["status"] == "complete" else 2
    except (Exception, KeyboardInterrupt) as error:
        atomic_text(args.output / "summary.json", canonical({"status": "cancelled" if isinstance(error, KeyboardInterrupt) else "failed", "generated_at": utcnow(),
            "source": "Acquisition/research failed; observations unavailable", "metrics": {}, "errors": [str(error) or type(error).__name__]}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
