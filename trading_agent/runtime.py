"""Local durable job service. MCP/UI connections never own the trading workers."""
import argparse
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import fcntl
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

from pydantic import Field, model_validator
from typing import Literal

from .config import AgentConfig, Settings
from .data import DataError, validate_yahoo_window
from .reporting import atomic_text


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = {"report.html", "report.md", "report.json", "performance.png", "executions.png", "daily_pnl.png", "equity.csv", "fills.csv", "decisions.json"}


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
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


class JobManager:
    def __init__(self, root=None, *, spawn=subprocess.Popen):
        self.root = Path(root or runtime_root()).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lease = (self.root / "runtime.lock").open("a")
        try:
            fcntl.flock(self.lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lease.close()
            raise ValueError("A runtime already owns this trading data directory") from None
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.root / "jobs.sqlite", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, request TEXT, status TEXT, created_at TEXT, updated_at TEXT, error TEXT)")
        self.db.execute("UPDATE jobs SET status='interrupted', updated_at=?, error=? WHERE status IN ('running','stopping')",
                        (_now(), "Runtime restarted. Review the last saved positions and reports before starting a new simulation; intraday state is not resumed."))
        self.db.commit()
        self.processes, self.threads = {}, []
        self.spawn = spawn
        self.closing = False

    def _update(self, job_id, status, error=None):
        self.db.execute("UPDATE jobs SET status=?, updated_at=?, error=? WHERE id=?", (status, _now(), error, job_id))
        self.db.commit()

    def start(self, value):
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
            process.stdin.close()
        with self.lock:
            row = self.db.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
            record = _read(self.root / job_id / "output/summary.json")
            stopped = row["status"] == "stopping"
            status = "stopped" if stopped else "complete" if code == 0 and record and record["status"] == "complete" else "failed"
            error = None if status != "failed" else "; ".join(record.get("errors", [])) if record else f"Worker exited with code {code}; inspect its local worker.log"
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
        result["report"] = {key: report[key] for key in ["status", "generated_at", "source", "metrics", "errors"]} if report else None
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

    def stop(self, job_id):
        with self.lock:
            self.get(job_id)
            process = self.processes.get(job_id)
            if process and self.db.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()[0] != "stopping":
                self._update(job_id, "stopping")
                process.send_signal(signal.SIGTERM)
        return self.get(job_id)

    def artifact(self, job_id, name):
        self.get(job_id)
        if name not in ARTIFACTS:
            raise KeyError("Unknown report artifact")
        path = self.root / job_id / "output" / name
        if not path.is_file():
            raise KeyError("Report artifact is not ready")
        return path

    def close(self):
        with self.lock:
            self.closing = True
            ids = list(self.processes)
        for job_id in ids:
            self.stop(job_id)
        for process in list(self.processes.values()):
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for thread in self.threads:
            thread.join()
        self.db.close()
        self.lease.close()


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
                parts = self.path.strip("/").split("/")
                if self.command == "POST":
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 <= length <= 65536:
                        raise ValueError("Request exceeds 64 KB")
                    body = json.loads(self.rfile.read(length) or b"{}")
                    if parts == ["jobs"]:
                        result = manager.start(body)
                    elif len(parts) == 3 and parts[0] == "jobs" and parts[2] == "stop":
                        result = manager.stop(parts[1])
                    else:
                        raise KeyError("Unknown endpoint")
                elif parts == ["jobs"]:
                    result = manager.list()
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
            except KeyError as error:
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
    args = parser.parse_args()
    manager = JobManager()
    server = create_server(manager, port=args.port)
    def stop(_signal, _frame):
        threading.Thread(target=server.shutdown, daemon=True).start()
    for value in [signal.SIGINT, signal.SIGTERM]:
        signal.signal(value, stop)
    print(f"Trading runtime: http://127.0.0.1:{server.server_port} (simulation only)", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        manager.close()


if __name__ == "__main__":
    main()
