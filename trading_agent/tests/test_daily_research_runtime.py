"""Daily research is bounded and owned by the durable runtime, not MCP."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
import subprocess
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from trading_agent.runtime import JobManager, create_server, runtime_token
from trading_agent.tests.test_runtime import Worker


class DailyResearchRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.manager = JobManager(self.directory.name, spawn=Worker)

    def tearDown(self):
        self.manager.close()
        self.directory.cleanup()

    def test_dispatch_preserves_request_and_returns_bounded_snapshot_and_provenance(self):
        job = self.manager.start({"mode": "daily_research", "daily_research": {"symbols": ["SPY", "IEF", "GLD"]}})
        worker = self.manager.processes[job["id"]]
        command = worker.command
        self.assertIn("trading_agent.daily_research", command)
        self.assertIn("--runtime-worker", command)
        self.assertEqual(Path(command[command.index("--root") + 1]), Path(self.directory.name).resolve() / "research")
        self.assertEqual(command[command.index("--experiment-id") + 1], job["id"])
        request = json.loads(Path(command[command.index("--request") + 1]).read_text())
        self.assertEqual(request["daily_research"]["symbols"], ["SPY", "IEF", "GLD"])
        self.assertIsNone(self.manager.daily_research(job["id"])["daily_research"])
        output = Path(self.directory.name) / job["id"] / "output"
        output.mkdir()
        report = {"status": "complete", "experiment_id": job["id"], "assessment": "inconclusive",
                  "promotion_status": "research_only", "provenance_ref": "daily/manifest.json", "errors": []}
        for name in ["daily-study.json", "summary.json"]:
            (output / name).write_text(json.dumps(report))
        (output / "data-manifest.json").write_text('{"source":"yahoo"}')
        worker.done.set()
        self.manager.threads[-1].join(2)
        result = self.manager.daily_research(job["id"])
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["report"]["promotion_status"], "research_only")
        self.assertEqual(result["daily_research"], report)
        self.assertEqual(self.manager.artifact(job["id"], "daily-study.json"), (output / "daily-study.json").resolve())
        self.assertIn("data-manifest.json", result["artifacts"])
        with self.assertRaises(KeyError):
            self.manager.artifact(job["id"], "../../token")

    def test_invalid_or_mixed_payload_creates_no_job(self):
        for payload in [
            {"mode": "daily_research"},
            {"mode": "daily_research", "daily_research": {}, "dataset": {"start": "2026-01-01", "end": "2026-01-02"}},
            {"mode": "daily_research", "daily_research": {"symbols": ["SPY", "QQQ", "IEF", "GLD"]}},
            {"mode": "daily_research", "daily_research": {"data_start": "2020-01-01", "development_start": "2010-01-01"}},
        ]:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                self.manager.start(payload)
        self.assertEqual(self.manager.list()["jobs"], [])

    def test_daily_status_rejects_other_modes_and_generic_cancel_preserves_evidence(self):
        demo = self.manager.start({})
        with self.assertRaises(KeyError):
            self.manager.daily_research(demo["id"])
        job = self.manager.start({"mode": "daily_research", "daily_research": {}})
        output = Path(self.directory.name) / job["id"] / "output"
        output.mkdir()
        snapshot = b'{"status":"running","attempts":[{"status":"complete"}]}'
        (output / "daily-study.json").write_bytes(snapshot)
        self.manager.stop(job["id"])
        self.manager.threads[-1].join(2)
        stopped = self.manager.daily_research(job["id"])
        self.assertEqual(stopped["status"], "stopped")
        self.assertEqual(stopped["daily_research"]["status"], "stopped")
        self.assertEqual((output / "daily-study.json").read_bytes(), snapshot)

    def test_restart_does_not_replay_or_claim_a_stale_snapshot_is_active(self):
        job = self.manager.start({"mode": "daily_research", "daily_research": {}})
        output = Path(self.directory.name) / job["id"] / "output"
        output.mkdir()
        snapshot = b'{"status":"running","assessment":"inconclusive","attempts":[]}'
        (output / "daily-study.json").write_bytes(snapshot)
        (output / "summary.json").write_bytes(snapshot)
        self.manager.stop(job["id"])
        self.manager.threads[-1].join(2)
        self.manager.db.execute("UPDATE jobs SET status='running' WHERE id=?", (job["id"],))
        self.manager.db.commit()
        self.manager.close()
        self.manager = JobManager(self.directory.name, spawn=Worker)
        result = self.manager.daily_research(job["id"])
        self.assertEqual(result["status"], "interrupted")
        self.assertEqual(result["daily_research"]["status"], "interrupted")
        self.assertEqual(result["daily_research"]["last_saved_status"], "running")
        self.assertEqual(result["report"]["status"], "interrupted")
        self.assertIn("unknown", result["daily_research"]["operational_notice"])
        self.assertEqual((output / "daily-study.json").read_bytes(), snapshot)
        self.assertFalse(self.manager.processes)

    def test_http_daily_start_status_and_list_are_scoped(self):
        token = runtime_token(Path(self.directory.name))
        server = create_server(self.manager, port=0, token=token)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f"http://127.0.0.1:{server.server_port}/daily-research"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        with urlopen(Request(url, data=b'{"symbols":["SPY","IEF","GLD"]}', headers=headers)) as response:
            job = json.load(response)
        with urlopen(Request(url + "/" + job["id"], headers=headers)) as response:
            result = json.load(response)
        self.assertEqual(result["id"], job["id"])
        self.assertIn("daily_research", result)
        with urlopen(Request(url, headers=headers)) as response:
            self.assertEqual([item["id"] for item in json.load(response)["jobs"]], [job["id"]])
        with self.assertRaises(HTTPError) as caught:
            urlopen(Request(url + "/../token", headers=headers))
        self.assertEqual(caught.exception.code, 404)

    def test_real_daily_worker_completes_from_cached_fixture_without_provider_access(self):
        from trading_agent.daily_research import DailyResearchSpec, acquire_daily
        from trading_agent.tests.test_daily_screen import fixture
        spec = DailyResearchSpec(data_start="2019-01-02", development_start="2020-01-02", validation_start="2021-01-04",
                                 development_end="2022-12-30", lookbacks=[63], cost_bps=[5])
        frames = fixture(spec.data_start, spec.development_end)
        class FixtureTicker:
            def __init__(self, symbol): self.symbol = symbol
            def history(self, **_kwargs): return frames[self.symbol].copy()
            def get_history_metadata(self): return {"currency": "USD", "exchangeTimezoneName": "America/New_York"}
        _, manifest = acquire_daily(spec, self.manager.root / "research/daily-studies" / ("f" * 32) / "dataset", ticker_factory=FixtureTicker)
        # Patch the provider before the CLI imports its default factory. Cache
        # discovery failures must fail this offline test, never access Yahoo.
        bootstrap = """import runpy, sys, yfinance
def unavailable(*args, **kwargs):
    raise AssertionError('Offline fixture worker attempted provider access')
yfinance.Ticker = unavailable
sys.argv = ['trading_agent.daily_research', *sys.argv[1:]]
runpy.run_module('trading_agent.daily_research', run_name='__main__')
"""
        def spawn(command, **kwargs):
            return subprocess.Popen([command[0], "-c", bootstrap, *command[3:]], **kwargs)
        self.manager.spawn = spawn
        job = self.manager.start({"mode": "daily_research", "daily_research": spec.model_dump()})
        worker = self.manager.processes[job["id"]]
        code = worker.wait(timeout=45)
        self.manager.threads[-1].join(2)
        log = (self.manager.root / job["id"] / "worker.log").read_text()
        self.assertEqual(code, 0, log)
        result = self.manager.daily_research(job["id"])
        self.assertEqual(result["status"], "complete", log)
        self.assertEqual(result["daily_research"]["dataset_id"], manifest["dataset_id"])
        self.assertFalse(result["daily_research"]["reserved_final"]["accessed"])
        self.assertEqual(result["daily_research"]["promotion_status"], "research_only")
        self.assertEqual(len(result["daily_research"]["attempts"]), 8)
        self.assertTrue(all(item["reconciliation"]["ok"] for item in result["daily_research"]["attempts"]))
        self.assertIn("data-manifest.json", result["artifacts"])


if __name__ == "__main__":
    unittest.main()
