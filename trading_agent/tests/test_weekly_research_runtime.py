"""Frozen weekly research crosses MCP/HTTP without transferring worker ownership."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from trading_agent.runtime import JobManager, create_server, runtime_token
from trading_agent.tests.test_runtime import Worker


UNIVERSE = ["SPY", "IWM", "QQQ", "EFA", "EEM", "IEF", "TLT", "GLD", "DBC"]


class WeeklyResearchRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.manager = JobManager(self.directory.name, spawn=Worker)

    def tearDown(self):
        self.manager.close()
        self.directory.cleanup()

    def test_protocol_and_envelope_fail_before_any_worker_or_request_exists(self):
        invalid = [{"source": "synthetic"}, {"symbols": UNIVERSE[::-1]}, {"symbols": ["SPY"]},
                   {"data_start": "2007-01-04"}, {"development_start": "2009-01-02"},
                   {"validation_start": "2014-01-02"}, {"development_end": "2023-12-29"},
                   {"reserved_final_start": "2024-01-02"}, {"reserved_final_end": "2026-01-02"},
                   {"initial_cash": 99999}, {"cost_bps": [5]}, {"cost_bps": [5, 10, 30]},
                   {"lookback": 10}, {"holdings": 2}, {"finalize": True}, {"interval": "1d"}]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.manager.start({"mode": "weekly_research", "weekly_research": value})
        for value in [{"mode": "weekly_research"},
                      {"mode": "weekly_research", "weekly_research": {}, "daily_research": {}},
                      {"mode": "weekly_research", "weekly_research": {}, "sector_research": {}},
                      {"mode": "daily_research", "daily_research": {}, "weekly_research": {}}]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.manager.start(value)
        self.assertEqual(self.manager.list()["jobs"], [])
        self.assertFalse(self.manager.processes)
        self.assertEqual(list(Path(self.directory.name).glob("*/request.json")), [])

    def test_independent_dispatch_receipt_and_completed_provenance(self):
        job = self.manager.start({"mode": "weekly_research", "weekly_research": {}})
        worker = self.manager.processes[job["id"]]
        self.assertIn("trading_agent.weekly_research", worker.command)
        self.assertIn("--runtime-worker", worker.command)
        saved = json.loads(Path(worker.command[worker.command.index("--request") + 1]).read_text())
        self.assertEqual(saved["weekly_research"]["symbols"], UNIVERSE)
        self.assertEqual(saved["weekly_research"]["data_start"], "2007-01-03")
        self.assertEqual(saved["weekly_research"]["development_start"], "2008-01-02")
        self.assertEqual(saved["weekly_research"]["cost_bps"], [5, 10, 20])
        self.assertTrue(job["simulation_only"])
        self.assertIsNone(self.manager.weekly_research(job["id"])["daily_research"])
        output = Path(self.directory.name) / job["id"] / "output"
        output.mkdir()
        snapshot = {"status": "complete", "experiment_id": job["id"], "assessment": "inconclusive",
                    "promotion_status": "research_only", "reserved_final": {"accessed": False},
                    "provenance_ref": "daily-studies/fixture/dataset/manifest.json", "errors": []}
        for name in ["daily-study.json", "summary.json"]:
            (output / name).write_text(json.dumps(snapshot))
        worker.done.set()
        self.manager.threads[-1].join(2)
        result = self.manager.weekly_research(job["id"])
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["daily_research"], snapshot)
        self.assertEqual(result["report"]["provenance_ref"], snapshot["provenance_ref"])
        self.assertEqual(self.manager.artifact(job["id"], "daily-study.json"), (output / "daily-study.json").resolve())

    def test_stop_and_restart_relabel_snapshot_without_mutating_saved_evidence(self):
        job = self.manager.start({"mode": "weekly_research", "weekly_research": {}})
        output = Path(self.directory.name) / job["id"] / "output"
        output.mkdir()
        snapshot = b'{"status":"running","attempts":[{"status":"complete"}]}'
        for name in ["daily-study.json", "summary.json"]:
            (output / name).write_bytes(snapshot)
        monitor = self.manager.threads[-1]
        self.manager.stop(job["id"])
        monitor.join(2)
        self.assertFalse(monitor.is_alive())
        stopped = self.manager.weekly_research(job["id"])
        self.assertEqual(stopped["status"], "stopped")
        self.assertEqual(stopped["daily_research"]["status"], "stopped")
        self.assertEqual(stopped["daily_research"]["attempts"], [{"status": "complete"}])
        self.manager.db.execute("UPDATE jobs SET status='running' WHERE id=?", (job["id"],))
        self.manager.db.commit()
        self.manager.close()
        self.manager = JobManager(self.directory.name, spawn=Worker)
        restored = self.manager.weekly_research(job["id"])
        self.assertEqual(restored["status"], "interrupted")
        self.assertEqual(restored["daily_research"]["status"], "interrupted")
        self.assertEqual(restored["daily_research"]["last_saved_status"], "running")
        self.assertIn("unknown", restored["daily_research"]["operational_notice"])
        self.assertFalse(self.manager.processes)
        self.assertEqual((output / "daily-study.json").read_bytes(), snapshot)

    def test_http_lists_and_status_isolate_all_three_study_modes(self):
        token = runtime_token(Path(self.directory.name))
        server = create_server(self.manager, port=0, token=token)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_port}"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        def call(path, body=None):
            with urlopen(Request(base + path, data=json.dumps(body).encode() if body is not None else None, headers=headers)) as response:
                return json.load(response)

        jobs = {}
        for mode in ["weekly", "sector", "daily"]:
            jobs[mode] = call(f"/{mode}-research", {})
            monitor = self.manager.threads[-1]
            self.manager.stop(jobs[mode]["id"])
            monitor.join(2)
            self.assertFalse(monitor.is_alive())
        for mode in jobs:
            self.assertEqual([job["id"] for job in call(f"/{mode}-research")["jobs"]], [jobs[mode]["id"]])
            for requested in jobs:
                path = f"/{mode}-research/{jobs[requested]['id']}"
                if requested == mode:
                    self.assertIn("daily_research", call(path))
                else:
                    with self.subTest(path=path), self.assertRaises(HTTPError) as caught:
                        call(path)
                    self.assertEqual(caught.exception.code, 404)
        for body in [{"cost_bps": [0]}, {"finalize": True}, {"development_end": "2025-12-31"}]:
            with self.subTest(body=body), self.assertRaises(HTTPError) as caught:
                call("/weekly-research", body)
            self.assertEqual(caught.exception.code, 400)
        self.assertEqual(len(self.manager.list()["jobs"]), 3)


if __name__ == "__main__":
    unittest.main()
