import json
from pathlib import Path
import signal
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from trading_agent.runtime import JobManager, JobRequest, create_server, runtime_token
from trading_agent.data import DataError


class Worker:
    def __init__(self, command, **_kwargs):
        self.command = command
        self.done = threading.Event()
        self.code = 0
    def wait(self, timeout=None):
        if not self.done.wait(timeout):
            raise TimeoutError()
        return self.code
    def send_signal(self, value):
        self.signal = value
        self.code = 2
        self.done.set()
    def kill(self):
        self.done.set()


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.manager = JobManager(self.directory.name, spawn=Worker)

    def tearDown(self):
        self.manager.close()
        self.directory.cleanup()

    def test_validation_bounds_and_watch_date_conflicts(self):
        for value in [{"mode": "real"}, {"continuous": True}, {"mode": "watch", "start": "2026-10-14"}, {"start": "2026-99-99"},
                      {"end": "2026-10-14"}, {"config": {"initial_cash": -1}}, {"mode": "watch", "sessions": 0}]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.manager.start(value)
        self.assertEqual(JobRequest(mode="watch", continuous=True).sessions, 1)

    def test_unsupported_yahoo_window_creates_neither_job_nor_worker(self):
        with self.assertRaisesRegex(DataError, "recent 30 days"):
            self.manager.start({"mode": "backtest", "start": "2026-01-01", "end": "2026-10-01", "config": {"symbols": ["AAPL"], "interval": "1m", "initial_cash": 100}})
        self.assertEqual(self.manager.list(), {"jobs": []})
        self.assertFalse(self.manager.processes)
        self.assertEqual(list(Path(self.directory.name).glob("*/config.json")), [])

    def test_background_lifecycle_atomic_progress_and_stop_are_persistent(self):
        job = self.manager.start({"mode": "watch", "continuous": True})
        self.assertEqual(job["status"], "running")
        self.assertTrue(job["simulation_only"])
        worker = self.manager.processes[job["id"]]
        self.assertIn("--continuous", worker.command)
        output = Path(self.directory.name) / job["id"] / "output"
        output.mkdir()
        (output / "progress.json").write_text(json.dumps({"completed_bars": 1, "holdings": {"SPY": {"quantity": 1}}}))
        self.assertEqual(self.manager.get(job["id"])["progress"]["completed_bars"], 1)
        (output / "report.html").write_text("<h1>Simulation</h1>")
        self.assertEqual(self.manager.artifact(job["id"], "report.html").read_text(), "<h1>Simulation</h1>")
        for bad in ["../../token", "config.json", "worker.log"]:
            with self.assertRaises(KeyError): self.manager.artifact(job["id"], bad)
        self.manager.stop(job["id"])
        self.manager.threads[-1].join(2)
        self.assertEqual(worker.signal, signal.SIGTERM)
        self.assertEqual(self.manager.get(job["id"])["status"], "stopped")
        self.assertEqual(len(self.manager.list()["jobs"]), 1)
        self.assertEqual(self.manager.get(job["id"])["progress"]["holdings"]["SPY"]["quantity"], 1)

    def test_worker_limit_and_single_runtime_ownership(self):
        self.manager.start({}); self.manager.start({})
        with self.assertRaisesRegex(ValueError, "already running"): self.manager.start({})
        with self.assertRaisesRegex(ValueError, "already owns"): JobManager(self.directory.name)
        for bad in ["../token", "unknown", "0" * 32]:
            with self.assertRaises(KeyError): self.manager.get(bad)

    def test_restart_labels_unfinished_work_instead_of_silently_replaying_positions(self):
        job = self.manager.start({})
        worker = self.manager.processes[job["id"]]
        worker.code = -9; worker.done.set()
        self.manager.threads[-1].join(2)
        self.manager.db.execute("UPDATE jobs SET status='running' WHERE id=?", (job["id"],))
        self.manager.db.commit()
        self.manager.close()
        self.manager = JobManager(self.directory.name, spawn=Worker)
        restored = self.manager.get(job["id"])
        self.assertEqual(restored["status"], "interrupted")
        self.assertIn("not resumed", restored["error"])
        self.assertFalse(self.manager.processes)

    def test_runtime_http_requires_token_and_returns_useful_errors(self):
        token = runtime_token(Path(self.directory.name))
        self.assertEqual(token, runtime_token(Path(self.directory.name)))
        server = create_server(self.manager, port=0, token=token)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f"http://127.0.0.1:{server.server_port}"
        with self.assertRaises(HTTPError) as caught: urlopen(f"{url}/jobs")
        self.assertEqual(caught.exception.code, 401)
        with urlopen(Request(f"{url}/jobs", headers={"Authorization": f"Bearer {token}"})) as response:
            self.assertEqual(json.load(response), {"jobs": []})
        with self.assertRaises(HTTPError) as caught:
            urlopen(Request(f"{url}/jobs", data=b'{"mode":"real"}', headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}))
        self.assertEqual(caught.exception.code, 400)
        with self.assertRaises(HTTPError) as caught:
            urlopen(Request(f"{url}/jobs", data=json.dumps({"mode": "backtest", "start": "2026-01-01", "end": "2026-10-01", "config": {"interval": "1m"}}).encode(), headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}))
        self.assertEqual(caught.exception.code, 400)
        self.assertIn("recent 30 days", json.load(caught.exception)["error"])

    def test_retained_multi_batch_range_starts_a_worker_with_original_dates(self):
        from unittest.mock import patch
        with patch("trading_agent.data.datetime") as clock:
            from datetime import datetime, timezone
            clock.now.return_value = datetime(2026, 10, 15, 20, tzinfo=timezone.utc)
            job = self.manager.start({"mode": "backtest", "start": "2026-10-01", "end": "2026-10-14", "config": {"symbols": ["AAPL"], "interval": "1m"}})
        self.assertEqual(job["status"], "running")
        self.assertEqual(job["request"]["start"], "2026-10-01")
        self.assertEqual(job["request"]["end"], "2026-10-14")
        self.assertEqual(job["request"]["config"]["interval"], "1m")

    def test_real_worker_exits_when_runtime_lifetime_pipe_closes(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = JobManager(directory)
            try:
                job = manager.start({"mode": "demo", "start": "2026-10-14", "config": {"symbols": ["DEMO_A"]}})
                worker = manager.processes[job["id"]]
                worker.stdin.close()  # The same EOF a runtime crash delivers.
                self.assertNotEqual(worker.wait(timeout=10), 0)
                manager.threads[-1].join(2)
                self.assertEqual(manager.get(job["id"])["status"], "failed")
            finally:
                manager.close()


if __name__ == "__main__":
    unittest.main()
