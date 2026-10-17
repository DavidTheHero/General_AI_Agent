import builtins
import errno
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from trading_agent import filelock
from trading_agent.filelock import FileLease, LeaseBusy
from trading_agent.runtime import JobManager


CHILD_SCRIPT = """
import sys
from trading_agent.filelock import FileLease, LeaseBusy

path = sys.argv[1]
try:
    lease = FileLease(path)
except LeaseBusy:
    print("busy")
else:
    print("acquired")
    lease.release()
"""


CHILD_HOLD_SCRIPT = """
import sys
import time
from trading_agent.filelock import FileLease

path = sys.argv[1]
marker = sys.argv[2]
lease = FileLease(path)
with open(marker, "w", encoding="utf-8") as handle:
    handle.write("ready")
time.sleep(30)
"""


class RuntimeLockTests(unittest.TestCase):
    def test_parent_holds_lease_and_child_reports_busy_then_acquires(self):
        with tempfile.TemporaryDirectory() as directory:
            lock_path = Path(directory) / "runtime.lock"
            lease = FileLease(lock_path)
            try:
                result = subprocess.run(
                    [sys.executable, "-c", CHILD_SCRIPT, str(lock_path)],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                self.assertEqual(result.returncode, 0)
                self.assertIn("busy", result.stdout)
            finally:
                lease.release()

            result = subprocess.run(
                [sys.executable, "-c", CHILD_SCRIPT, str(lock_path)],
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 0)
            self.assertIn("acquired", result.stdout)

    def test_child_holds_lease_parent_polls_marker_and_kills_child(self):
        with tempfile.TemporaryDirectory() as directory:
            lock_path = Path(directory) / "runtime.lock"
            marker_path = Path(directory) / "ready.marker"
            child = subprocess.Popen(
                [sys.executable, "-c", CHILD_HOLD_SCRIPT, str(lock_path), str(marker_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                deadline = time.monotonic() + 10.0
                while not marker_path.exists():
                    if time.monotonic() > deadline:
                        self.fail("Child did not write READY marker in time")
                    time.sleep(0.05)

                with self.assertRaises(LeaseBusy):
                    FileLease(lock_path)

                child.kill()
                child.wait(timeout=5)
                child.communicate(timeout=5)

                lease = FileLease(lock_path)
                lease.release()
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=5)
                child.communicate(timeout=5)

    def test_same_process_contention_and_idempotent_close(self):
        with tempfile.TemporaryDirectory() as directory:
            lock_path = Path(directory) / "runtime.lock"
            lease = FileLease(lock_path)
            try:
                with self.assertRaises(LeaseBusy):
                    FileLease(lock_path)
            finally:
                lease.release()
                lease.release()

            lease = FileLease(lock_path)
            lease.release()

    def test_paths_with_spaces_and_unicode(self):
        with tempfile.TemporaryDirectory(prefix="test dir \u00e9\u00fc") as directory:
            lock_path = Path(directory) / "my lock \u00e9\u00fc.lock"
            lease = FileLease(lock_path)
            try:
                with self.assertRaises(LeaseBusy):
                    FileLease(lock_path)
            finally:
                lease.release()

            lease = FileLease(lock_path)
            lease.release()

    def test_jobmanager_retries_after_operational_error(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch("trading_agent.runtime.sqlite3.connect", side_effect=sqlite3.OperationalError("injected")):
                with self.assertRaisesRegex(sqlite3.OperationalError, "injected"):
                    JobManager(directory)

            manager = JobManager(directory)
            manager.close()

    def test_reconciliation_failure_closes_connection(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = JobManager(directory)
            manager.db.execute(
                "INSERT INTO jobs VALUES (?,?,?,?,?,?)",
                ("a" * 32, '{"mode":"experiment"}', "running", "now", "now", None),
            )
            manager.db.commit()
            manager.close()

            original_connect = sqlite3.connect
            captured = []

            def fake_connect(*args, **kwargs):
                conn = original_connect(*args, **kwargs)
                captured.append(conn)
                return conn

            with mock.patch("trading_agent.research.reconcile_interrupted", side_effect=RuntimeError("boom")):
                with mock.patch("trading_agent.runtime.sqlite3.connect", side_effect=fake_connect):
                    with self.assertRaises(RuntimeError):
                        JobManager(directory)

            self.assertEqual(len(captured), 1)
            with self.assertRaises(sqlite3.ProgrammingError):
                captured[0].execute("SELECT 1")

            manager = JobManager(directory)
            manager.close()

    def test_platform_lock_error_propagates_and_closes_handle(self):
        with tempfile.TemporaryDirectory() as directory:
            lock_path = Path(directory) / "runtime.lock"
            original_open = builtins.open
            opened_handles = []

            def tracking_open(*args, **kwargs):
                handle = original_open(*args, **kwargs)
                opened_handles.append(handle)
                return handle

            lock_target = (
                "trading_agent.filelock.msvcrt.locking"
                if os.name == "nt"
                else "trading_agent.filelock.fcntl.flock"
            )
            with mock.patch("builtins.open", side_effect=tracking_open):
                with mock.patch(lock_target, side_effect=OSError(errno.EIO, "I/O error")):
                    with self.assertRaises(OSError) as context:
                        FileLease(lock_path)
                    self.assertNotIsInstance(context.exception, LeaseBusy)
                    self.assertEqual(context.exception.errno, errno.EIO)

            self.assertEqual(len(opened_handles), 1)
            for handle in opened_handles:
                self.assertTrue(handle.closed)


if __name__ == "__main__":
    unittest.main()
