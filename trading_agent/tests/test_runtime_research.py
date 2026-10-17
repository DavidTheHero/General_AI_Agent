"""Research jobs use the same durable, connection-independent worker lifecycle."""
import json
from pathlib import Path
import sqlite3
from contextlib import closing
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from trading_agent.runtime import JobManager, create_server, runtime_token
from trading_agent.tests.test_runtime import Worker


DATASET = {"source": "synthetic", "symbols": ["DEMO_A"], "start": "2026-10-01", "end": "2026-10-14", "interval": "30m", "seed": 17}


class ResearchRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.manager = JobManager(self.directory.name, spawn=Worker)

    def tearDown(self):
        self.manager.close()
        self.directory.cleanup()

    def test_dataset_request_is_persisted_before_spawn_and_runs_outside_mcp(self):
        captured = []
        def spawn(command, **kwargs):
            request_path = Path(command[command.index("--request") + 1])
            captured.append(json.loads(request_path.read_text()))
            return Worker(command, **kwargs)
        self.manager.spawn = spawn
        job = self.manager.start({"mode": "dataset", "dataset": DATASET})
        self.assertEqual(job["status"], "running")
        self.assertEqual(captured[0]["dataset"]["start"], DATASET["start"])
        self.assertEqual(captured[0]["dataset"]["interval"], DATASET["interval"])
        command = self.manager.processes[job["id"]].command
        self.assertIn("trading_agent.research", command)
        self.assertIn("--runtime-worker", command)
        self.assertEqual(command[command.index("--experiment-id") + 1], job["id"])
        self.assertTrue(job["simulation_only"])

    def test_experiment_cancellation_and_restart_retain_request_without_replay(self):
        experiment = {"dataset_id": "a" * 64, "config": {"symbols": ["DEMO_A"], "interval": "30m"},
                      "candidates": [{"kind": "trend_following"}], "train_sessions": 2, "validation_sessions": 1, "final_sessions": 2}
        job = self.manager.start({"mode": "experiment", "experiment": experiment})
        stopped = self.manager.stop(job["id"])
        self.manager.threads[-1].join(2)
        self.assertIn(stopped["status"], {"stopping", "stopped"})
        self.assertEqual(self.manager.get(job["id"])["status"], "stopped")
        self.assertIn("before a final report", self.manager.get(job["id"])["error"])
        self.manager.db.execute("UPDATE jobs SET status='running' WHERE id=?", (job["id"],))
        self.manager.db.commit()
        self.manager.close()
        self.manager = JobManager(self.directory.name, spawn=Worker)
        restored = self.manager.get(job["id"])
        self.assertEqual(restored["status"], "interrupted")
        self.assertEqual(restored["request"]["experiment"]["dataset_id"], "a" * 64)
        self.assertFalse(self.manager.processes)

    def test_research_request_bounds_reject_before_creating_job(self):
        invalid = [
            {"mode": "dataset", "dataset": {**DATASET, "interval": "ticks"}},
            {"mode": "dataset", "dataset": DATASET, "experiment": {}},
            {"mode": "experiment", "experiment": {"dataset_id": "a" * 64}},
        ]
        for request in invalid:
            with self.subTest(request=request), self.assertRaises(ValueError):
                self.manager.start(request)
        self.assertEqual(self.manager.list(), {"jobs": []})
        self.assertEqual(list(Path(self.directory.name).glob("*/request.json")), [])

    def test_restart_reconciles_research_attempts_without_reopening_consumed_holdout(self):
        from trading_agent.research import _database, canonical, reconcile_interrupted
        dataset_id = "a" * 64
        specification = {"dataset_id": dataset_id, "config": {"symbols": ["DEMO_A"], "interval": "30m"},
                         "candidates": [{"kind": "trend_following"}], "train_sessions": 2, "validation_sessions": 1,
                         "final_sessions": 2, "finalize": True, "parent_experiment_id": "c" * 32}
        job = self.manager.start({"mode": "experiment", "experiment": specification})
        job_id = job["id"]
        research_root = Path(self.directory.name) / "research"
        directory = research_root / "experiments" / job_id
        directory.mkdir(parents=True)
        attempts = [{"attempt_id": f"{job_id}-{index:04}", "status": "running",
                     "artifact_ref": f"experiments/{job_id}/{job_id}-{index:04}.json"} for index in [1, 2]]
        # The second DB registration preceded the last experiment snapshot.
        record = {"experiment_id": job_id, "dataset_id": dataset_id, "status": "running", "source": "SYNTHETIC fixture",
                  "generated_at": "2026-10-14T20:00:00Z", "metrics": {}, "errors": [], "attempts": attempts[:1],
                  "split": {"final_test_accessed": True}}
        (directory / "experiment.json").write_text(canonical(record))
        prior_events = "".join(canonical({"event": "started", **attempt}) + "\n" for attempt in attempts)
        (directory / "attempts.jsonl").write_text(prior_events)
        partial_path = directory / f"{attempts[1]['attempt_id']}.json"
        partial = b'{"sessions":[{"holdings":{"DEMO_A":{"quantity":2}},"fills":[]}]}'
        partial_path.write_bytes(partial)
        output = Path(self.directory.name) / job_id / "output"
        output.mkdir()
        progress = b'{"holdings":{"DEMO_A":{"quantity":2}},"fills":[],"completed_bars":12}'
        (output / "progress.json").write_bytes(progress)
        database = _database(research_root)
        database.execute("INSERT INTO holdouts VALUES (?,?,?)", (dataset_id, '["2026-10-13","2026-10-14"]', job_id))
        for attempt in attempts:
            database.execute("INSERT INTO attempts VALUES (?,?,?,?,?)", (attempt["attempt_id"], job_id, canonical(attempt), "running", None))
        database.commit()
        database.close()
        # Dispose of the fixture worker, then restore the crash-persisted job state.
        self.manager.stop(job_id)
        self.manager.threads[-1].join(2)
        self.manager.db.execute("UPDATE jobs SET status='stopping' WHERE id=?", (job_id,))
        self.manager.db.commit()
        self.manager.close()
        self.manager = JobManager(self.directory.name, spawn=Worker)
        restored = self.manager.experiment(job_id)
        self.assertEqual(restored["status"], "interrupted")
        self.assertEqual(restored["report"]["status"], "interrupted")
        self.assertEqual(restored["experiment"]["status"], "interrupted")
        reconciled = restored["experiment"]["attempts"]
        self.assertEqual([attempt["status"] for attempt in reconciled], ["interrupted", "interrupted"])
        self.assertEqual([attempt["artifact_available"] for attempt in reconciled], [False, True])
        self.assertIn("not resumed", reconciled[0]["error"])
        self.assertEqual((output / "progress.json").read_bytes(), progress)
        self.assertEqual(partial_path.read_bytes(), partial)
        events = (directory / "attempts.jsonl").read_text()
        self.assertTrue(events.startswith(prior_events))
        self.assertEqual([event["event"] for event in map(json.loads, events.splitlines())], ["started", "started", "restart_reconciled", "restart_reconciled"])
        self.assertEqual((output / "attempts.jsonl").read_text(), events)
        with closing(sqlite3.connect(research_root / "research.sqlite")) as database, database:
            self.assertEqual(database.execute("SELECT opened_by FROM holdouts WHERE dataset_id=?", (dataset_id,)).fetchone()[0], job_id)
            rows = database.execute("SELECT status,result FROM attempts ORDER BY id").fetchall()
            self.assertTrue(all(status == "interrupted" and json.loads(result)["status"] == "interrupted" for status, result in rows))
        self.assertFalse(self.manager.processes)
        # A repeated reconciliation is idempotent and does not append new warnings.
        before = (directory / "experiment.json").read_text()
        reconcile_interrupted(research_root, [job_id])
        self.assertEqual(len(json.loads(before)["errors"]), len(json.loads((directory / "experiment.json").read_text())["errors"]))
        self.assertEqual((directory / "attempts.jsonl").read_text(), events)
        # An event append can precede a crash before metadata/SQLite commits.
        # Reprocessing that earlier state must not duplicate the durable event.
        (directory / "experiment.json").write_text(canonical(record))
        with closing(sqlite3.connect(research_root / "research.sqlite")) as database, database:
            database.execute("UPDATE attempts SET status='running',result=NULL")
        reconcile_interrupted(research_root, [job_id])
        self.assertEqual((directory / "attempts.jsonl").read_text(), events)

    def test_http_strategy_discovery_validation_and_research_limits(self):
        token = runtime_token(Path(self.directory.name))
        server = create_server(self.manager, port=0, token=token)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f"http://127.0.0.1:{server.server_port}"
        def get(path):
            with urlopen(Request(url + path, headers={"Authorization": f"Bearer {token}"})) as response:
                return json.load(response)
        strategies = get("/strategies")["strategies"]
        self.assertTrue(any(strategy["id"] == "trend_following" for strategy in strategies))
        for path in ["/datasets?limit=51", "/experiments?limit=0"]:
            with self.subTest(path=path), self.assertRaises(HTTPError) as caught:
                get(path)
            self.assertEqual(caught.exception.code, 400)
        with urlopen(Request(url + "/strategies/validate", data=b'{"kind":"mean_reversion"}',
                             headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})) as response:
            self.assertEqual(json.load(response)["config"]["kind"], "mean_reversion")


if __name__ == "__main__":
    unittest.main()
