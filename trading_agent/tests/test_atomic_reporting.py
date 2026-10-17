import errno
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from trading_agent import reporting
from trading_agent.fileio import open_snapshot


class AtomicTextTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.path = Path(self.tmpdir.name) / "report.json"

    def test_unicode_utf8_exact_read_and_repeated_replacement(self):
        content = "café 研究 – test"
        for i in range(5):
            reporting.atomic_text(self.path, content)
            self.assertEqual(self.path.read_text(encoding="utf-8"), content)
        leftovers = [p for p in self.path.parent.iterdir() if p.name.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_mocked_replace_permission_error_once_then_success(self):
        original_replace = reporting.replace_snapshot
        call_count = 0

        def fake_replace(self, target):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise PermissionError(13, "Access is denied.")
            return original_replace(self, target)

        with mock.patch.object(reporting, "_WINDOWS", True), mock.patch.object(reporting, "replace_snapshot", fake_replace):
            reporting.atomic_text(self.path, "hello")

        self.assertEqual(self.path.read_text(encoding="utf-8"), "hello")
        leftovers = [p for p in self.path.parent.iterdir() if p.name.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_persistent_permission_error_bounded_original_intact_temp_cleaned(self):
        self.path.write_text("original", encoding="utf-8")
        original_replace = reporting.replace_snapshot

        def fake_replace(self, target):
            raise PermissionError(13, "Access is denied.")

        start = time.monotonic()
        with mock.patch.object(reporting, "_WINDOWS", True), mock.patch.object(reporting, "replace_snapshot", fake_replace):
            with self.assertRaises(PermissionError):
                reporting.atomic_text(self.path, "new")
        elapsed = time.monotonic() - start
        self.assertGreaterEqual(elapsed, 0.9)
        self.assertLess(elapsed, 2.0)

        self.assertEqual(self.path.read_text(encoding="utf-8"), "original")
        leftovers = [p for p in self.path.parent.iterdir() if p.name.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_non_permission_error_immediately_propagated(self):
        self.path.write_text("original", encoding="utf-8")

        def fake_replace(self, target):
            raise OSError(errno.EIO, "I/O error")

        with mock.patch.object(reporting, "replace_snapshot", fake_replace):
            with self.assertRaises(OSError):
                reporting.atomic_text(self.path, "new")

        self.assertEqual(self.path.read_text(encoding="utf-8"), "original")
        leftovers = [p for p in self.path.parent.iterdir() if p.name.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_real_concurrent_writer_and_readers(self):
        self.path.write_text("{}", encoding="utf-8")
        writer_errors = []
        reader_errors = []
        successful_snapshots = []
        stop = threading.Event()

        def writer():
            for i in range(200):
                try:
                    reporting.atomic_text(self.path, json.dumps({"gen": i}))
                except Exception as e:
                    writer_errors.append(e)
                    return

        def reader():
            while not stop.is_set():
                try:
                    with open_snapshot(self.path) as stream:
                        text = stream.read()
                    data = json.loads(text)
                    if "gen" in data:
                        successful_snapshots.append(data["gen"])
                except OSError:
                    pass
                except json.JSONDecodeError:
                    reader_errors.append("JSONDecodeError")
                    return
                except Exception as e:
                    reader_errors.append(e)
                    return

        reader_threads = [threading.Thread(target=reader) for _ in range(2)]
        writer_thread = threading.Thread(target=writer)
        for t in reader_threads:
            t.start()
        writer_thread.start()
        try:
            writer_thread.join(timeout=10)
        finally:
            stop.set()
            for t in reader_threads:
                t.join(timeout=5)
            writer_thread.join(timeout=5)
        for t in reader_threads + [writer_thread]:
            self.assertFalse(t.is_alive())

        self.assertEqual(writer_errors, [])
        self.assertEqual(reader_errors, [])
        self.assertGreaterEqual(len(successful_snapshots), 1)
        final = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(final["gen"], 199)
        leftovers = [p for p in self.path.parent.iterdir() if p.name.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_open_snapshot_retains_old_content_while_destination_is_replaced(self):
        self.path.write_text("old", encoding="utf-8")
        with open_snapshot(self.path) as stream:
            reporting.atomic_text(self.path, "new")
            self.assertEqual(stream.read(), "old")
        self.assertEqual(self.path.read_text(encoding="utf-8"), "new")

    @unittest.skipUnless(os.name == "nt", "Windows-only held read handle test")
    def test_readonly_destination_is_not_overwritten(self):
        self.path.write_text("immutable", encoding="utf-8")
        self.path.chmod(0o444)
        try:
            with self.assertRaises(PermissionError):
                reporting.atomic_text(self.path, "replacement")
            self.assertEqual(self.path.read_text(encoding="utf-8"), "immutable")
        finally:
            self.path.chmod(0o644)

    @unittest.skipUnless(os.name == "nt", "Windows-only held read handle test")
    def test_windows_persistent_held_handle_denial_then_write_after_close(self):
        self.path.write_text("original", encoding="utf-8")
        f = open(self.path, "r", encoding="utf-8")
        try:
            with self.assertRaises(PermissionError):
                reporting.atomic_text(self.path, "new")
        finally:
            f.close()

        time.sleep(0.1)
        reporting.atomic_text(self.path, "new")
        self.assertEqual(self.path.read_text(encoding="utf-8"), "new")
        leftovers = [p for p in self.path.parent.iterdir() if p.name.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    @unittest.skipUnless(os.name == "nt", "Windows-only held read handle test")
    def test_windows_reader_open_handle_release_after_delay(self):
        self.path.write_text("original", encoding="utf-8")
        f = open(self.path, "r", encoding="utf-8")
        release_thread = threading.Thread(target=lambda: (time.sleep(0.1), f.close()))
        release_thread.start()
        try:
            start = time.monotonic()
            reporting.atomic_text(self.path, "new")
            elapsed = time.monotonic() - start
            self.assertGreaterEqual(elapsed, 0.08)
            self.assertLess(elapsed, 2.0)
            self.assertEqual(self.path.read_text(encoding="utf-8"), "new")
        finally:
            release_thread.join(timeout=5)
            self.assertFalse(release_thread.is_alive())
        leftovers = [p for p in self.path.parent.iterdir() if p.name.endswith(".tmp")]
        self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
