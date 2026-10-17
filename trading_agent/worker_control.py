"""Portable worker cancellation helper (stdlib only).

Provides ``install_worker_control`` which installs signal handlers and an
optional stdin-EOF watcher so that worker processes can be cancelled
portably across POSIX and Windows without ``os.kill`` / ``TerminateProcess``.
"""
import _thread
import os
import signal
import sys
import threading
import time


def install_worker_control(runtime_worker: bool):
    """Install portable cancellation handlers.

    Parameters
    ----------
    runtime_worker:
        When True, a daemon watcher thread blocks on
        ``os.read(sys.stdin.fileno(), 1)`` until EOF.  On EOF (or read
        error) it requests a one-shot ``KeyboardInterrupt`` on the main
        thread via ``_thread.interrupt_main()``.

    Returns
    -------
    object
        A controller with a ``sleep(seconds)`` method backed by
        ``threading.Event.wait`` so the watcher can wake the main thread
        before the pending interrupt is delivered.
    """
    _wake = threading.Event()
    _fired = [False]

    def _handler(_signum, _frame):
        raise KeyboardInterrupt()

    signal.signal(signal.SIGTERM, _handler)
    signal.signal(signal.SIGINT, _handler)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _handler)

    def _request_interrupt():
        if _fired[0]:
            return
        _fired[0] = True
        # Schedule the interrupt first so it is pending by the time the
        # main thread wakes from Event.wait and resumes bytecode execution.
        _thread.interrupt_main()
        _wake.set()

    if runtime_worker:
        def _watcher():
            try:
                while os.read(sys.stdin.fileno(), 1):
                    pass
            except (OSError, ValueError):
                pass
            _request_interrupt()

        threading.Thread(target=_watcher, daemon=True).start()

    def sleep(seconds):
        # Windows Python 3.11/3.12 lock waits defer pending console signals.
        # Return to bytecode regularly even without a parent-pipe EOF wakeup.
        if seconds < 0:
            raise ValueError("sleep length must be non-negative")
        deadline = time.monotonic() + seconds
        remaining = seconds
        while remaining > 0 and not _wake.wait(min(remaining, .2)):
            remaining = deadline - time.monotonic()

    class _Controller:
        """Minimal controller exposing ``sleep``."""
        pass

    ctrl = _Controller()
    ctrl.sleep = sleep
    return ctrl
