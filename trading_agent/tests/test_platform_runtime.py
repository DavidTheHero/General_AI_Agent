"""Offline lifecycle checks with real processes on Windows and macOS."""
import json
import os
from pathlib import Path
import socket
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from trading_agent.config import load_config
from trading_agent.fileio import open_snapshot
from trading_agent.runtime import JobManager, _read, create_server, main


ROOT = Path(__file__).resolve().parents[2]
REQUEST = {"mode": "demo", "start": "2026-10-14", "config": {"symbols": ["DEMO_A"], "interval": "5m",
           "strategy": {"kind": "buy_and_hold"}}}
SLOW_WORKER = """import runpy,sys,time
from pathlib import Path
from trading_agent.engine import IntradayAgent
original=IntradayAgent.observe
def observe(self,*args,**kwargs):
 result=original(self,*args,**kwargs)
 time.sleep(.12)
 return result
IntradayAgent.observe=observe
sys.argv=['trading_agent',*sys.argv[1:]]
output=Path(sys.argv[sys.argv.index('--output')+1])
try: runpy.run_module('trading_agent',run_name='__main__')
finally: (output.parent/'worker-exited').write_text('exited',encoding='utf-8')
"""


def slow_spawn(command, **kwargs):
    return subprocess.Popen([command[0], "-c", SLOW_WORKER, *command[3:]], **kwargs)


def wait_for(function, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = function()
        if result:
            return result
        time.sleep(.03)
    raise AssertionError("Timed out waiting for worker state")


class ChildExit:
    """Retain a Windows process handle so exit checks cannot target a reused PID."""
    def __init__(self, pid):
        self.pid = pid
        if os.name == "nt":
            import ctypes
            self.api = ctypes.WinDLL("kernel32", use_last_error=True)
            self.api.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
            self.api.OpenProcess.restype = ctypes.c_void_p
            self.api.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
            self.api.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
            self.api.CloseHandle.argtypes = [ctypes.c_void_p]
            self.handle = self.api.OpenProcess(0x100001, False, pid)
            if not self.handle:
                raise ctypes.WinError(ctypes.get_last_error())

    def exited(self):
        if os.name == "nt":
            return self.api.WaitForSingleObject(self.handle, 0) == 0
        try:
            os.kill(self.pid, 0)
        except ProcessLookupError:
            return True
        return False

    def close(self):
        try:
            if not self.exited():
                if os.name == "nt":
                    self.api.TerminateProcess(self.handle, 1)
                else:
                    os.kill(self.pid, signal.SIGKILL)
                wait_for(self.exited, 5)
        finally:
            if os.name == "nt":
                self.api.CloseHandle(self.handle)


class PlatformRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="runtime spaces ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def manager(self, **kwargs):
        manager = JobManager(self.root, **kwargs)
        self.addCleanup(manager.close)
        return manager

    def progress(self, manager, job_id):
        def observed():
            progress = manager.get(job_id)["progress"]
            return progress if progress and progress["completed_bars"] >= 4 else None
        return wait_for(observed)

    def test_parent_eof_wakes_one_hour_wait_and_runs_cleanup(self):
        ready = self.root / "ready"
        code = """from trading_agent.worker_control import install_worker_control
from pathlib import Path
import sys
control=install_worker_control(True)
Path(sys.argv[1]).touch()
try: control.sleep(3600)
except KeyboardInterrupt:
 print('graceful cleanup',flush=True)
 sys.exit(2)
"""
        process = subprocess.Popen([sys.executable, "-c", code, str(ready)], cwd=ROOT,
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            wait_for(ready.exists, 10)
            process.stdin.close()
            process.stdin = None
            output, error = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 2, error)
            self.assertIn("graceful cleanup", output)
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)

    def test_direct_cli_sleep_observes_pending_interrupt_without_parent_pipe(self):
        code = """import _thread,threading
from trading_agent.worker_control import install_worker_control
control=install_worker_control(False)
threading.Timer(.1,_thread.interrupt_main).start()
try: control.sleep(3600)
except KeyboardInterrupt: print('interrupt observed',flush=True)
"""
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("interrupt observed", result.stdout)

    def test_cancel_retains_actual_open_holdings_and_partial_report(self):
        manager = self.manager(spawn=slow_spawn)
        job = manager.start(REQUEST)
        progress = self.progress(manager, job["id"])
        self.assertGreater(progress["holdings"]["DEMO_A"]["quantity"], 0)
        manager.stop(job["id"])
        final = wait_for(lambda: (value if (value := manager.get(job["id"]))["status"] == "stopped" else None))
        self.assertEqual(final["report"]["status"], "partial")
        self.assertGreater(final["progress"]["holdings"]["DEMO_A"]["quantity"], 0)
        report = _read(self.root / job["id"] / "output/report.json")
        self.assertEqual(report["metrics"]["completed_sessions"], 0)
        self.assertFalse(report["sessions"][0]["finished"])
        self.assertEqual(report["sessions"][0]["fills"], final["progress"]["fills"])

    def test_blocked_worker_is_forced_after_bounded_grace_with_explicit_notice(self):
        def blocked(command, **kwargs):
            return subprocess.Popen([command[0], "-c", "import time;time.sleep(300)"], **kwargs)
        manager = self.manager(spawn=blocked, stop_timeout=.2)
        job = manager.start(REQUEST)
        worker = manager.processes[job["id"]]
        started = time.monotonic()
        manager.stop(job["id"])
        self.assertLess(time.monotonic() - started, .5)
        result = wait_for(lambda: (value if (value := manager.get(job["id"]))["status"] == "stopped" else None), 5)
        self.assertIsNotNone(worker.poll())
        self.assertIn("Forced termination", result["error"])
        self.assertIn("no work is resumed", result["error"])

    def test_close_waits_for_active_worker_and_releases_ownership_idempotently(self):
        manager = self.manager(spawn=slow_spawn)
        job = manager.start(REQUEST)
        worker = manager.processes[job["id"]]
        self.progress(manager, job["id"])
        manager.close()
        manager.close()
        self.assertIsNotNone(worker.poll())
        self.assertFalse(any(thread.is_alive() for thread in manager.threads))
        replacement = self.manager()
        self.assertEqual(replacement.get(job["id"])["status"], "stopped")
        self.assertFalse(replacement.processes)

    def test_server_binds_loopback_without_reverse_dns_lookup(self):
        def blocked(*_args, **_kwargs):
            raise AssertionError("loopback binding must not perform a reverse DNS lookup")
        with patch.object(socket, "getfqdn", blocked):
            manager = self.manager()
            server = create_server(manager, port=0)
            self.addCleanup(server.server_close)
            self.assertEqual(server.server_address[0], "127.0.0.1")
            self.assertGreater(server.server_port, 0)
            self.assertEqual(server.server_name, "127.0.0.1")
        with socket.socket() as probe:
            probe.settimeout(2)
            probe.connect((server.server_name, server.server_port))

    def test_bind_failure_closes_database_and_lease(self):
        with socket.socket() as occupied:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                occupied.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            occupied.bind(("127.0.0.1", 0))
            occupied.listen()
            with patch.dict(os.environ, {"TRADING_DATA_DIR": str(self.root)}), \
                    patch.object(sys, "argv", ["runtime", "--port", str(occupied.getsockname()[1])]):
                with self.assertRaises(OSError):
                    main()
        self.manager().close()

    def test_owner_crash_stops_worker_and_recovers_without_replaying_snapshot(self):
        bootstrap = """import json,sys,time,subprocess
from pathlib import Path
from trading_agent.runtime import JobManager
manager=JobManager(sys.argv[1],spawn=lambda command,**kwargs:subprocess.Popen([command[0],'-c',sys.argv[2],*command[3:]],**kwargs))
job=manager.start(json.loads(sys.argv[3]))
Path(sys.argv[1],'ready.json').write_text(json.dumps({'id':job['id'],'pid':manager.processes[job['id']].pid}),encoding='utf-8')
time.sleep(300)
"""
        with (self.root / "owner.log").open("wb") as log:
            owner = subprocess.Popen([sys.executable, "-c", bootstrap, str(self.root), SLOW_WORKER, json.dumps(REQUEST)],
                                     cwd=ROOT, stdout=log, stderr=log)
        job_dir = None
        child = None
        try:
            job = wait_for(lambda: _read(self.root / "ready.json"))
            child = ChildExit(job["pid"])
            job_dir = self.root / job["id"]
            progress_path = job_dir / "output/progress.json"
            wait_for(lambda: (p if (p := _read(progress_path)) and p["completed_bars"] >= 4 else None))
            owner.kill()
            owner.wait(timeout=5)
            wait_for((job_dir / "worker-exited").exists, 15)
            wait_for(child.exited, 15)
            snapshot = progress_path.read_bytes()
            manager = self.manager()
            result = manager.get(job["id"])
            self.assertEqual(result["status"], "interrupted")
            self.assertFalse(manager.processes)
            self.assertEqual(progress_path.read_bytes(), snapshot)
            self.assertGreater(result["progress"]["holdings"]["DEMO_A"]["quantity"], 0)
        finally:
            if owner.poll() is None:
                owner.kill()
                owner.wait(timeout=5)
            if child:
                child.close()

    def test_utf8_configuration_and_snapshot_preserve_non_ascii(self):
        path = self.root / "config.json"
        name = "mod\u00e8le-\u7814\u7a76"
        path.write_text(json.dumps({"strategy": {"model": name}}, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(load_config(path).strategy.model, name)
        path.write_text(json.dumps({"source": name}, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(_read(path), {"source": name})
        with open_snapshot(path) as stream:
            self.assertEqual(json.load(stream), {"source": name})


if __name__ == "__main__":
    unittest.main()
