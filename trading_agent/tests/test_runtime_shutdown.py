"""Regression tests for JobManager.close shutdown serialization and failure retention (WIN-02-F1)."""
import subprocess
import sys
import tempfile
import threading
import unittest

from trading_agent.runtime import JobManager

READER = "import sys; sys.stdin.buffer.read()"


class RuntimeShutdownTests(unittest.TestCase):
    def make_manager(self, root):
        children = []

        def spawn(_command, **kwargs):
            child = subprocess.Popen([sys.executable, "-c", READER], **kwargs)
            children.append(child)
            return child

        return JobManager(root, spawn=spawn, stop_timeout=2), children

    def test_concurrent_close_is_serialized(self):
        with tempfile.TemporaryDirectory(prefix="rt shutdown ") as root:
            manager, children = self.make_manager(root)
            job_id = manager.start({"mode": "demo"})["id"]
            original_stop = manager.stop
            paused = threading.Event()
            b_started = threading.Event()
            b_done = threading.Event()
            proceed = threading.Event()

            def gated_stop(job_id):
                if threading.current_thread().name == "close-A":
                    paused.set()
                    self.assertTrue(proceed.wait(10), "release gate expired while the first close was paused")
                return original_stop(job_id)

            manager.stop = gated_stop
            a_errors, b_errors = [], []
            a_thread = b_thread = None
            replacement = None

            def close_a():
                try:
                    manager.close()
                except Exception as error:
                    a_errors.append(error)

            def close_b():
                b_started.set()
                try:
                    manager.close()
                except Exception as error:
                    b_errors.append(error)
                finally:
                    b_done.set()

            try:
                a_thread = threading.Thread(target=close_a, name="close-A")
                a_thread.start()
                self.assertTrue(paused.wait(5), "first close never reached its stop gate")
                b_thread = threading.Thread(target=close_b, name="close-B")
                b_thread.start()
                self.assertTrue(b_started.wait(5), "second close never began")
                self.assertFalse(b_done.wait(2), "second close returned while the first close was paused; shutdown is not serialized")
                proceed.set()
                a_thread.join(10)
                self.assertFalse(a_thread.is_alive(), "first close did not finish after release")
                b_thread.join(10)
                self.assertFalse(b_thread.is_alive(), "second close did not finish after release")
                self.assertEqual(a_errors, [], "first close raised: %r" % (a_errors,))
                self.assertEqual(b_errors, [], "second close raised: %r" % (b_errors,))
                self.assertTrue(manager.closed, "manager did not finish closing")
                self.assertTrue(all(child.poll() is not None for child in children), "owned worker did not exit")
                self.assertTrue(all(not thread.is_alive() for thread in manager.threads), "manager monitor or deadline threads did not end")
                replacement = JobManager(root)
                self.assertEqual(replacement.get(job_id)["status"], "stopped")
                self.assertEqual(replacement.processes, {}, "restarted runtime replayed the stopped job")
                manager.close()
            finally:
                proceed.set()
                manager.stop = original_stop
                for child in children:
                    if child.poll() is None:
                        child.kill()
                    child.wait(timeout=5)
                for thread in (a_thread, b_thread):
                    if thread is not None and thread.is_alive():
                        thread.join(5)
                self.assertFalse(any(thread is not None and thread.is_alive() for thread in (a_thread, b_thread)), "close thread remained alive in cleanup")
                if not manager.closed:
                    manager.close()
                if replacement is not None and not replacement.closed:
                    replacement.close()

    def test_failed_close_retains_worker_and_lease_until_retry(self):
        with tempfile.TemporaryDirectory(prefix="rt fail ") as root:
            manager, children = self.make_manager(root)
            job_id = manager.start({"mode": "demo"})["id"]
            original_stop = manager.stop

            def failing_stop(_job_id):
                raise RuntimeError("injected stop failure")

            retry_thread = None
            retry_errors = []
            retry_done = threading.Event()
            replacement = None
            unexpected_owner = None

            def retry_close():
                try:
                    manager.close()
                except Exception as error:
                    retry_errors.append(error)
                finally:
                    retry_done.set()

            try:
                manager.stop = failing_stop
                with self.assertRaisesRegex(RuntimeError, "injected stop failure"):
                    manager.close()
                self.assertFalse(manager.closed, "closed was set even though the first close failed")
                self.assertTrue(all(child.poll() is None for child in children), "owned worker exited despite the failed close")
                self.assertEqual(manager.get(job_id)["status"], "running", "DB is not usable after a failed close")
                try:
                    unexpected_owner = JobManager(root)
                except ValueError as error:
                    self.assertIn("already owns", str(error), "failed close released the lease: %r" % (error,))
                    unexpected_owner = None
                else:
                    unexpected_owner.close()
                    self.fail("failed close released the lease; a second runtime owner was created")
                manager.stop = original_stop
                retry_thread = threading.Thread(target=retry_close, name="close-retry", daemon=True)
                retry_thread.start()
                self.assertTrue(retry_done.wait(5), "retry close did not finish within five seconds")
                retry_thread.join(5)
                self.assertFalse(retry_thread.is_alive(), "retry close thread remained alive")
                self.assertEqual(retry_errors, [], "retry close raised: %r" % (retry_errors,))
                self.assertTrue(manager.closed, "manager did not close on retry")
                self.assertTrue(all(child.poll() is not None for child in children), "owned worker did not exit on retry")
                self.assertTrue(all(not thread.is_alive() for thread in manager.threads), "manager monitor or deadline threads did not end")
                replacement = JobManager(root)
                self.assertEqual(replacement.get(job_id)["status"], "stopped")
                self.assertEqual(replacement.processes, {}, "restarted runtime replayed the stopped job")
            finally:
                manager.stop = original_stop
                for child in children:
                    if child.poll() is None:
                        child.kill()
                    child.wait(timeout=5)
                if retry_thread is not None and retry_thread.is_alive():
                    retry_thread.join(5)
                self.assertFalse(any(thread is not None and thread.is_alive() for thread in (retry_thread,)), "close thread remained alive in cleanup")
                if not manager.closed:
                    manager.close()
                if unexpected_owner is not None and not unexpected_owner.closed:
                    unexpected_owner.close()
                if replacement is not None and not replacement.closed:
                    replacement.close()
