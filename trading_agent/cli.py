"""Run with python -m trading_agent or the installed intraday-agent command."""
import argparse
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sys
import signal
import os
import threading
from uuid import uuid4

from .calendar import MarketCalendar
from .config import load_config
from .data import SyntheticFeed
from .runner import run_backtest, run_watch


def main(argv=None):
    parser = argparse.ArgumentParser(description="Autonomous intraday simulation and executive reporting; no broker orders")
    parser.add_argument("mode", choices=["backtest", "watch", "demo"])
    parser.add_argument("--config", type=Path, help="Validated JSON configuration; defaults to SPY/AAPL and SMA policy")
    parser.add_argument("--start", help="First NYSE session date (inclusive); backtest/demo only")
    parser.add_argument("--end", help="Last NYSE session date (inclusive); defaults to start")
    parser.add_argument("--sessions", type=int, default=1, help="Number of upcoming sessions to poll in watch mode")
    parser.add_argument("--continuous", action="store_true", help="Watch upcoming sessions until stopped")
    parser.add_argument("--runtime-worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--output", type=Path, help="New report directory (existing nonempty directories are rejected)")
    args = parser.parse_args(argv)
    if args.continuous and args.mode != "watch":
        parser.error("--continuous applies only to watch")
    def interrupt(_signal, _frame):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, interrupt)
    if args.runtime_worker:
        def parent_lifetime():
            while os.read(sys.stdin.fileno(), 1):
                pass
            os.kill(os.getpid(), signal.SIGTERM)
        threading.Thread(target=parent_lifetime, daemon=True).start()
    logger = logging.getLogger("trading_agent")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        config = load_config(args.config)
        if args.mode == "demo" and not args.config:
            config = config.model_copy(update={"symbols": ["DEMO_A", "DEMO_B"]})
        calendar = MarketCalendar()
        output = args.output or Path("artifacts/trading") / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}"
        if output.exists() and any(output.iterdir()):
            raise ValueError("Output directory is not empty; choose a new directory to preserve previous reports")
        if args.mode == "watch":
            if args.start or args.end:
                raise ValueError("watch uses upcoming market sessions; date ranges belong to backtest")
            record = run_watch(config, output, session_count=None if args.continuous else args.sessions, calendar=calendar)
        else:
            if args.sessions != 1:
                raise ValueError("--sessions applies only to watch; use date ranges for backtest/demo")
            if args.end and not args.start:
                raise ValueError("--end requires --start")
            start = args.start or calendar.latest_completed().date
            end = args.end or start
            feed = SyntheticFeed(calendar.sessions(start, end)) if args.mode == "demo" else None
            record = run_backtest(config, start, end, output, feed=feed, calendar=calendar)
        print(json.dumps({"status": record["status"], "source": record["source"], "report": str((output / "report.html").resolve()), "metrics": record["metrics"], "errors": record["errors"]}, indent=2, allow_nan=False))
        return 0 if record["status"] == "complete" else 2
    except Exception as error:
        print(f"Simulation could not start: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
