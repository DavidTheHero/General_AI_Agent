"""The frozen sector study is owned by the runtime and has scoped interfaces."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from trading_agent.runtime import JobManager, create_server, runtime_token
from trading_agent.tests.test_runtime import Worker


class SectorResearchRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.manager = JobManager(self.directory.name, spawn=Worker)

    def tearDown(self):
        self.manager.close()
        self.directory.cleanup()

    def test_frozen_hypothesis_is_validated_before_a_worker_exists(self):
        for value in [{}, {"lookbacks": [63]}, {"top_k": 2}, {"finalize": True}, {"initial_cash": 99999},
                      {"data_start": "2001-01-02"}, {"validation_start": "2014-01-02"},
                      {"development_end": "2023-12-29"}, {"reserved_final_start": "2024-01-02"},
                      {"reserved_final_end": "2026-01-02"}, {"cost_bps": [5]}, {"cost_bps": [5, 10, 30]},
                      {"symbols": ["SPY"]}]:
            payload = {"mode": "sector_research", "sector_research": value}
            if not value:
                payload.pop("sector_research")
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.manager.start(payload)
        with self.assertRaises(ValueError):
            self.manager.start({"mode": "sector_research", "sector_research": {}, "daily_research": {}})
        self.assertEqual(self.manager.list()["jobs"], [])
        self.assertEqual(list(Path(self.directory.name).glob("*/request.json")), [])

    def test_dispatch_snapshot_artifacts_completion_and_scope(self):
        job = self.manager.start({"mode": "sector_research", "sector_research": {}})
        worker = self.manager.processes[job["id"]]
        self.assertIn("trading_agent.sector_research", worker.command)
        self.assertIn("--runtime-worker", worker.command)
        request = json.loads(Path(worker.command[worker.command.index("--request") + 1]).read_text())
        self.assertEqual(request["sector_research"]["symbols"], ["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY", "SPY"])
        self.assertEqual(request["sector_research"]["cost_bps"], [5, 10, 20])
        self.assertIsNone(self.manager.sector_research(job["id"])["daily_research"])
        with self.assertRaises(KeyError):
            self.manager.daily_research(job["id"])
        output = Path(self.directory.name) / job["id"] / "output"
        output.mkdir()
        snapshot = {"status": "complete", "experiment_id": job["id"], "assessment": "inconclusive",
                    "promotion_status": "research_only", "reserved_final": {"accessed": False},
                    "provenance_ref": "sector-studies/fixture/dataset/manifest.json", "errors": []}
        for name in ["daily-study.json", "summary.json"]:
            (output / name).write_text(json.dumps(snapshot))
        worker.done.set()
        self.manager.threads[-1].join(2)
        result = self.manager.sector_research(job["id"])
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["daily_research"], snapshot)
        self.assertEqual(result["report"]["provenance_ref"], snapshot["provenance_ref"])
        self.assertEqual(self.manager.artifact(job["id"], "daily-study.json"), (output / "daily-study.json").resolve())

    def test_cancellation_and_restart_preserve_last_snapshot_without_replay(self):
        job = self.manager.start({"mode": "sector_research", "sector_research": {}})
        output = Path(self.directory.name) / job["id"] / "output"
        output.mkdir()
        snapshot = b'{"status":"running","attempts":[{"status":"complete"}]}'
        for name in ["daily-study.json", "summary.json"]:
            (output / name).write_bytes(snapshot)
        monitor = self.manager.threads[-1]
        self.manager.stop(job["id"])
        monitor.join(2)
        self.assertFalse(monitor.is_alive())
        stopped = self.manager.sector_research(job["id"])
        self.assertEqual(stopped["status"], "stopped")
        self.assertEqual(stopped["daily_research"]["status"], "stopped")
        self.assertEqual(stopped["daily_research"]["attempts"], [{"status": "complete"}])
        self.manager.db.execute("UPDATE jobs SET status='running' WHERE id=?", (job["id"],))
        self.manager.db.commit()
        self.manager.close()
        self.manager = JobManager(self.directory.name, spawn=Worker)
        result = self.manager.sector_research(job["id"])
        self.assertEqual(result["status"], "interrupted")
        self.assertEqual(result["daily_research"]["status"], "interrupted")
        self.assertEqual(result["daily_research"]["last_saved_status"], "running")
        self.assertIn("unknown", result["daily_research"]["operational_notice"])
        self.assertFalse(self.manager.processes)
        self.assertEqual((output / "daily-study.json").read_bytes(), snapshot)

    def test_http_start_list_status_and_mode_isolation(self):
        token = runtime_token(Path(self.directory.name))
        server = create_server(self.manager, port=0, token=token)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_port}"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        with urlopen(Request(base + "/sector-research", data=b'{}', headers=headers)) as response:
            job = json.load(response)
        with urlopen(Request(base + "/sector-research/" + job["id"], headers=headers)) as response:
            self.assertIn("daily_research", json.load(response))
        with urlopen(Request(base + "/sector-research", headers=headers)) as response:
            self.assertEqual([item["id"] for item in json.load(response)["jobs"]], [job["id"]])
        with urlopen(Request(base + "/daily-research", headers=headers)) as response:
            self.assertEqual(json.load(response)["jobs"], [])
        with self.assertRaises(HTTPError) as caught:
            urlopen(Request(base + "/daily-research/" + job["id"], headers=headers))
        self.assertEqual(caught.exception.code, 404)
        with self.assertRaises(HTTPError) as caught:
            urlopen(Request(base + "/sector-research", data=b'{"cost_bps":[0]}', headers=headers))
        self.assertEqual(caught.exception.code, 400)
        self.assertEqual(len(self.manager.list()["jobs"]), 1)


if __name__ == "__main__":
    unittest.main()
