"""Local durable job service. MCP/UI connections never own the trading workers."""
import argparse
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import signal
import sqlite3
import subprocess
import sys
import threading
from uuid import uuid4
from urllib.parse import parse_qs, urlsplit

from pydantic import Field, model_validator
from typing import Literal

from .config import AgentConfig, Settings
from .data import DataError, validate_yahoo_window
from .reporting import atomic_text
from .filelock import FileLease, LeaseBusy
from .fileio import open_snapshot


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = {"report.html", "report.md", "report.json", "summary.json", "experiment.json", "attempts.jsonl", "daily-study.json", "data-manifest.json", "performance.png", "executions.png", "daily_pnl.png", "equity.csv", "fills.csv", "decisions.json"}


def runtime_root():
    return Path(os.environ.get("TRADING_DATA_DIR", ROOT / "artifacts/trading/runtime")).resolve()


def runtime_token(root=None):
    root = root or runtime_root()
    root.mkdir(parents=True, exist_ok=True)
    path = root / "token"
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return path.read_text().strip()
    with os.fdopen(descriptor, "w") as stream:
        stream.write(secrets.token_hex(32))
    return path.read_text().strip()


class JobRequest(Settings):
    mode: Literal["demo", "backtest", "watch"] = "demo"
    config: AgentConfig = Field(default_factory=AgentConfig)
    start: str | None = None
    end: str | None = None
    sessions: int = Field(default=1, ge=1, le=252)
    continuous: bool = False

    @model_validator(mode="after")
    def valid_range(self):
        if self.mode == "watch" and (self.start or self.end):
            raise ValueError("watch uses upcoming sessions, not historical dates")
        if self.mode != "watch" and (self.continuous or self.sessions != 1):
            raise ValueError("continuous and sessions apply only to watch")
        if self.end and not self.start:
            raise ValueError("end requires start")
        for value in [self.start, self.end]:
            if value and (not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) or not date.fromisoformat(value)):
                raise ValueError("Use ISO dates YYYY-MM-DD")
        if self.start and self.end and self.start > self.end:
            raise ValueError("start must not be after end")
        return self


def _now():
    return datetime.now(timezone.utc).isoformat()


def _read(path):
    try:
        with open_snapshot(path) as stream:
            return json.load(stream)
    except (OSError, ValueError):
        return None


class JobManager:
    def __init__(self, root=None, *, spawn=subprocess.Popen, stop_timeout=10):
        self.root = Path(root or runtime_root()).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            self.lease = FileLease(self.root / "runtime.lock")
        except LeaseBusy:
            raise ValueError("A runtime already owns this trading data directory") from None
        try:
            self.lock = threading.RLock()
            self.close_lock = threading.Lock()
            self.db = sqlite3.connect(self.root / "jobs.sqlite", check_same_thread=False)
            self.db.row_factory = sqlite3.Row
            self.db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, request TEXT, status TEXT, created_at TEXT, updated_at TEXT, error TEXT)")
            abandoned = self.db.execute("SELECT id, request FROM jobs WHERE status IN ('running','stopping')").fetchall()
            research_ids = [row["id"] for row in abandoned if json.loads(row["request"])["mode"] == "experiment"]
            if research_ids:
                from .research import reconcile_interrupted
                reconciled = reconcile_interrupted(self.root / "research", research_ids)
                for job_id in research_ids:
                    output = self.root / job_id / "output"
                    output.mkdir(parents=True, exist_ok=True)
                    if job_id in reconciled:
                        record = reconciled[job_id]
                        atomic_text(output / "experiment.json", json.dumps(record, allow_nan=False))
                        atomic_text(output / "summary.json", json.dumps({key: value for key, value in record.items() if key not in {"environment", "attempts", "protocol"}}, allow_nan=False))
                    attempts = self.root / "research/experiments" / job_id / "attempts.jsonl"
                    if attempts.is_file():
                        atomic_text(output / "attempts.jsonl", attempts.read_text(encoding="utf-8"))
            self.db.execute("UPDATE jobs SET status='interrupted', updated_at=?, error=? WHERE status IN ('running','stopping')",
                            (_now(), "Runtime restarted. Review the last saved positions and reports before starting a new simulation; intraday state is not resumed."))
            self.db.commit()
            self.processes, self.threads = {}, []
            self.spawn = spawn
            self.closing = False
            self.closed = False
            self.stop_timeout = stop_timeout
            self.forced = set()
        except BaseException:
            if getattr(self, "db", None) is not None:
                try:
                    self.db.close()
                except Exception:
                    pass
            self.lease.release()
            raise

    def _update(self, job_id, status, error=None):
        self.db.execute("UPDATE jobs SET status=?, updated_at=?, error=? WHERE id=?", (status, _now(), error, job_id))
        self.db.commit()

    def start(self, value):
        research = isinstance(value, dict) and value.get("mode") in {"dataset", "experiment", "daily_research", "sector_research", "weekly_research"}
        if research:
            from .research import ResearchJobRequest
            request = ResearchJobRequest.model_validate(value)
        else:
            request = JobRequest.model_validate(value)
        if request.mode == "backtest" and request.start:
            validate_yahoo_window(request.start, request.end or request.start, request.config.interval)
        with self.lock:
            if self.closing:
                raise ValueError("Runtime is shutting down")
            if len(self.processes) >= 2:
                raise ValueError("Two simulations are already running; stop one before starting another")
            job_id = uuid4().hex
            directory = self.root / job_id
            directory.mkdir()
            atomic_text(directory / "request.json", request.model_dump_json())
            if research:
                module = f"trading_agent.{request.mode}" if request.mode in {"daily_research", "sector_research", "weekly_research"} else "trading_agent.research"
                command = [sys.executable, "-m", module, "--request", str(directory / "request.json"),
                           "--root", str(self.root / "research"), "--output", str(directory / "output"),
                           "--experiment-id", job_id, "--runtime-worker"]
            else:
                atomic_text(directory / "config.json", request.config.model_dump_json())
                command = [sys.executable, "-m", "trading_agent", request.mode, "--runtime-worker", "--config", str(directory / "config.json"), "--output", str(directory / "output")]
                if request.start:
                    command += ["--start", request.start]
                if request.end:
                    command += ["--end", request.end]
                if request.mode == "watch":
                    command += ["--continuous"] if request.continuous else ["--sessions", str(request.sessions)]
            now = _now()
            self.db.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?)", (job_id, request.model_dump_json(), "running", now, now, None))
            self.db.commit()
            try:
                with (directory / "worker.log").open("wb") as log:
                    process = self.spawn(command, cwd=ROOT, stdin=subprocess.PIPE, stdout=log, stderr=log)
                self.processes[job_id] = process
                monitor = threading.Thread(target=self._monitor, args=(job_id, process), daemon=True)
                self.threads.append(monitor)
                monitor.start()
            except Exception as error:
                self._update(job_id, "failed", str(error))
            return self.get(job_id)

    def _monitor(self, job_id, process):
        code = process.wait()
        if getattr(process, "stdin", None):
            try:
                process.stdin.close()
            except (OSError, ValueError):
                pass
        with self.lock:
            row = self.db.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
            record = _read(self.root / job_id / "output/summary.json")
            stopped = row["status"] == "stopping"
            forced = job_id in self.forced
            complete = (not forced) and code == 0 and record and record.get("status") == "complete"
            status = "complete" if complete else "stopped" if stopped else "failed"
            if forced and stopped:
                error = "Forced termination after deadline. Review the last atomic snapshot; no work is resumed."
            elif status == "stopped" and not record:
                error = "Cancelled before a final report was saved. Review the last atomic progress snapshot; missing results are unavailable and no work is resumed."
            elif status == "failed":
                error = "; ".join(record.get("errors", [])) if record else f"Worker exited with code {code}; inspect its local worker.log"
            else:
                error = None
            self._update(job_id, status, error or (f"Worker exited with code {code}; simulation did not complete, inspect the report" if status == "failed" else None))
            self.processes.pop(job_id, None)

    def get(self, job_id):
        if not re.fullmatch(r"[a-f0-9]{32}", job_id):
            raise KeyError("Unknown trading job")
        with self.lock:
            row = self.db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise KeyError("Unknown trading job")
            result = dict(row)
        result["request"] = json.loads(result["request"])
        output = self.root / job_id / "output"
        progress, report = _read(output / "progress.json"), _read(output / "summary.json")
        result["progress"] = progress
        result["report"] = {key: report[key] for key in ["status", "generated_at", "source", "metrics", "errors", "dataset_id", "experiment_id", "assessment", "promotion_status", "finalized", "protocol_id", "provenance_ref"] if key in report} if report else None
        result["artifacts"] = sorted(name for name in ARTIFACTS if (output / name).is_file())
        result["dashboard_url"] = f"/?trading_job={job_id}"
        result["simulation_only"] = True
        return result

    def list(self):
        with self.lock:
            rows = [dict(row) for row in self.db.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT 50")]
        for row in rows:
            row["request"] = json.loads(row["request"])
            row["dashboard_url"] = f"/?trading_job={row['id']}"
        return {"jobs": rows}

    def datasets(self, limit=20):
        from .datasets import DatasetStore
        return {"datasets": DatasetStore(self.root / "research/datasets").list(limit=limit)}

    def dataset(self, dataset_id):
        from .datasets import DatasetStore
        return DatasetStore(self.root / "research/datasets").inspect(dataset_id)

    def experiments(self, limit=20):
        from .research import list_experiments
        records = list_experiments(self.root / "research", limit=limit)
        jobs = [job for job in self.list()["jobs"] if job["request"]["mode"] == "experiment"][:limit]
        return {"experiments": records, "jobs": jobs}

    def experiment(self, job_id):
        from .research import inspect_experiment
        job = self.get(job_id)
        if job["request"]["mode"] != "experiment":
            raise KeyError("Unknown research experiment")
        try:
            job["experiment"] = inspect_experiment(self.root / "research", job_id)
        except (FileNotFoundError, KeyError):
            job["experiment"] = None
        return job

    def daily_research(self, job_id):
        return self._daily_study(job_id, "daily_research")

    def sector_research(self, job_id):
        return self._daily_study(job_id, "sector_research")

    def weekly_research(self, job_id):
        return self._daily_study(job_id, "weekly_research")

    def _daily_study(self, job_id, mode):
        job = self.get(job_id)
        if job["request"]["mode"] != mode:
            raise KeyError(f"Unknown {mode} job")
        job["daily_research"] = _read(self.root / job_id / "output/daily-study.json")
        if job["status"] in {"interrupted", "stopped", "failed"}:
            for snapshot in [job["daily_research"], job["report"]]:
                if snapshot and snapshot.get("status") in {"running", "stopping"}:
                    snapshot["last_saved_status"] = snapshot["status"]
                    snapshot["status"] = job["status"]
                    snapshot["operational_notice"] = "The worker is no longer active. This is the last saved snapshot; later observations are unknown and no work is replayed."
        return job

    def compare(self, experiment_ids):
        from .research import compare_experiments
        if not isinstance(experiment_ids, list) or not 2 <= len(experiment_ids) <= 6 or len(set(experiment_ids)) != len(experiment_ids):
            raise ValueError("Compare between two and six distinct experiment IDs")
        for job_id in experiment_ids:
            self.experiment(job_id)
        return compare_experiments(self.root / "research", experiment_ids)

    def attempt(self, experiment_id, attempt_id):
        from .research import inspect_attempt
        self.experiment(experiment_id)
        if not re.fullmatch(re.escape(experiment_id) + r"-\d{4}", attempt_id):
            raise ValueError("Use an exact attempt ID belonging to this experiment")
        return inspect_attempt(self.root / "research", experiment_id, attempt_id)

    def stop(self, job_id):
        with self.lock:
            self.get(job_id)
            process = self.processes.get(job_id)
            if process and self.db.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()[0] != "stopping":
                self._update(job_id, "stopping")
                if getattr(process, "stdin", None):
                    try:
                        process.stdin.close()
                    except (OSError, ValueError):
                        pass
                else:
                    process.send_signal(signal.SIGTERM)
                deadline = threading.Thread(target=self._deadline, args=(job_id, process), daemon=True)
                self.threads.append(deadline)
                deadline.start()
        return self.get(job_id)

    def _deadline(self, job_id, process):
        try:
            process.wait(timeout=self.stop_timeout)
        except (subprocess.TimeoutExpired, TimeoutError):
            with self.lock:
                if job_id in self.processes and process.poll() is None:
                    self.forced.add(job_id)
                    try:
                        process.kill()
                    except ProcessLookupError:
                        self.forced.discard(job_id)
                    except OSError as error:
                        self.forced.discard(job_id)
                        self._update(job_id, "stopping", f"Force stop failed: {error}. Worker may still be running; no work is resumed.")
            try:
                process.wait(timeout=5)
            except (subprocess.TimeoutExpired, TimeoutError):
                pass

    def artifact(self, job_id, name):
        self.get(job_id)
        if name not in ARTIFACTS:
            raise KeyError("Unknown report artifact")
        path = self.root / job_id / "output" / name
        if not path.is_file():
            raise KeyError("Report artifact is not ready")
        return path

    def close(self):
        with self.close_lock:
            self._shutdown()

    def _shutdown(self):
        with self.lock:
            if self.closed:
                return
            self.closing = True
            ids = list(self.processes)
        for job_id in ids:
            self.stop(job_id)
        for thread in self.threads:
            thread.join(timeout=self.stop_timeout + 5)
        with self.lock:
            alive_procs = [p for p in self.processes.values() if p.poll() is None]
            alive_threads = [t for t in self.threads if t.is_alive()]
        if alive_procs or alive_threads:
            raise RuntimeError("Workers did not exit within the deadline; lease and DB remain open")
        with self.lock:
            if self.closed:
                return
            try:
                self.db.close()
            finally:
                self.lease.close()
            self.closed = True


def create_server(manager, *, port=2612, token=None):
    token = token or runtime_token(manager.root)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def handle_request(self):
            try:
                if not hmac.compare_digest(self.headers.get("Authorization", ""), f"Bearer {token}"):
                    self.send_error(401)
                    return
                location = urlsplit(self.path)
                parts = location.path.strip("/").split("/")
                query = parse_qs(location.query)
                limit = int(query.get("limit", ["20"])[0])
                if not 1 <= limit <= 50:
                    raise ValueError("limit must be between 1 and 50")
                if self.command == "POST":
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 <= length <= 65536:
                        raise ValueError("Request exceeds 64 KB")
                    body = json.loads(self.rfile.read(length) or b"{}")
                    if parts == ["jobs"]:
                        result = manager.start(body)
                    elif parts == ["datasets"]:
                        result = manager.start({"mode": "dataset", "dataset": body})
                    elif parts == ["experiments"]:
                        result = manager.start({"mode": "experiment", "experiment": body})
                    elif parts == ["daily-research"]:
                        result = manager.start({"mode": "daily_research", "daily_research": body})
                    elif parts == ["sector-research"]:
                        result = manager.start({"mode": "sector_research", "sector_research": body})
                    elif parts == ["weekly-research"]:
                        result = manager.start({"mode": "weekly_research", "weekly_research": body})
                    elif parts == ["experiments", "compare"]:
                        if not isinstance(body, dict) or set(body) != {"experiment_ids"}:
                            raise ValueError("Provide experiment_ids only")
                        result = manager.compare(body["experiment_ids"])
                    elif parts == ["strategies", "validate"]:
                        from .registry import validate_strategy
                        result = validate_strategy(body)
                    elif len(parts) == 3 and parts[0] == "jobs" and parts[2] == "stop":
                        result = manager.stop(parts[1])
                    elif len(parts) == 3 and parts[0] == "experiments" and parts[2] == "stop":
                        manager.experiment(parts[1])
                        manager.stop(parts[1])
                        result = manager.experiment(parts[1])
                    else:
                        raise KeyError("Unknown endpoint")
                elif parts == ["jobs"]:
                    result = manager.list()
                elif parts == ["strategies"]:
                    from .registry import list_strategies
                    result = {"strategies": list_strategies()}
                elif parts == ["datasets"]:
                    result = manager.datasets(limit)
                elif len(parts) == 2 and parts[0] == "datasets":
                    result = manager.dataset(parts[1])
                elif parts == ["experiments"]:
                    result = manager.experiments(limit)
                elif len(parts) == 2 and parts[0] == "experiments":
                    result = manager.experiment(parts[1])
                elif parts == ["daily-research"]:
                    result = {"jobs": [job for job in manager.list()["jobs"] if job["request"]["mode"] == "daily_research"][:limit]}
                elif len(parts) == 2 and parts[0] == "daily-research":
                    result = manager.daily_research(parts[1])
                elif parts == ["sector-research"]:
                    result = {"jobs": [job for job in manager.list()["jobs"] if job["request"]["mode"] == "sector_research"][:limit]}
                elif len(parts) == 2 and parts[0] == "sector-research":
                    result = manager.sector_research(parts[1])
                elif parts == ["weekly-research"]:
                    result = {"jobs": [job for job in manager.list()["jobs"] if job["request"]["mode"] == "weekly_research"][:limit]}
                elif len(parts) == 2 and parts[0] == "weekly-research":
                    result = manager.weekly_research(parts[1])
                elif len(parts) == 4 and parts[0] == "experiments" and parts[2] == "attempts":
                    result = manager.attempt(parts[1], parts[3])
                elif len(parts) == 2 and parts[0] == "jobs":
                    result = manager.get(parts[1])
                elif len(parts) == 4 and parts[0] == "jobs" and parts[2] == "artifacts":
                    path = manager.artifact(parts[1], parts[3])
                    payload = path.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                else:
                    raise KeyError("Unknown endpoint")
                self.respond(200, result)
            except (KeyError, FileNotFoundError) as error:
                self.respond(404, {"error": str(error)})
            except (ValueError, TypeError, DataError) as error:
                self.respond(400, {"error": str(error)})
            except Exception:
                self.respond(500, {"error": "Trading runtime error; inspect the service log"})

        def respond(self, status, body):
            payload = json.dumps(body, allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        do_GET = handle_request
        do_POST = handle_request
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main():
    parser = argparse.ArgumentParser(description="Persistent local trading simulation runtime")
    parser.add_argument("--port", type=int, default=int(os.environ.get("TRADING_RUNTIME_PORT", "2612")))
    parser.add_argument("--parent-pipe", action="store_true", default=False)
    args = parser.parse_args()
    manager = JobManager()
    server = None
    try:
        server = create_server(manager, port=args.port)

        def stop(_signal, _frame):
            threading.Thread(target=server.shutdown, daemon=True).start()

        for value in [signal.SIGINT, signal.SIGTERM]:
            signal.signal(value, stop)
        if hasattr(signal, "SIGBREAK"):
            signal.signal(signal.SIGBREAK, stop)

        if args.parent_pipe:
            def _watch_parent_pipe():
                try:
                    sys.stdin.read()
                except Exception:
                    pass
                threading.Thread(target=server.shutdown, daemon=True).start()
            threading.Thread(target=_watch_parent_pipe, daemon=True).start()

        print(f"Trading runtime: http://127.0.0.1:{server.server_port} (simulation only)", flush=True)
        try:
            server.serve_forever()
        finally:
            server.server_close()
    finally:
        manager.close()


if __name__ == "__main__":
    main()
