"""Autonomous replay/polling jobs with per-session and aggregate reports."""
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import time
from itertools import count
from uuid import uuid4

import pandas as pd

from .calendar import MarketCalendar
from .data import DataError, YahooFinanceFeed, session_frames
from .datasets import canonical, checksum, frame_record
from .engine import IntradayAgent
from .reporting import atomic_text, write_report


def _utcnow():
    return pd.Timestamp(datetime.now(timezone.utc))


def _provenance(data):
    return {"retrieved_at": data.retrieved_at, "source": data.source, "instruments": data.metadata}


def _archived_yahoo_feed(output):
    """Archive each adapter response before validation, including failed polls."""
    directory = Path(output) / "source-responses"

    def capture(symbol, request, frame, metadata, error):
        directory.mkdir(parents=True, exist_ok=True)
        retrieved_at = _utcnow().isoformat()
        response = {"symbol": symbol, "request": request, "retrieved_at": retrieved_at, "metadata": metadata,
                    "frame": frame_record(frame) if frame is not None else None, "error": error,
                    "capture_level": "adapter DataFrame before normalization; original Yahoo HTTP bytes unavailable"}
        path = directory / f"{uuid4().hex}.json"
        with path.open("x", encoding="utf-8") as stream:
            stream.write(canonical(response))
            stream.flush()
            os.fsync(stream.fileno())
        path.chmod(0o444)
        with (directory / "index.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(canonical({"file": path.name, "sha256": checksum(path), "retrieved_at": retrieved_at, "symbol": symbol}) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    return YahooFinanceFeed(response_sink=capture)


def _archive_provenance():
    return {"raw_capture_ref": "source-responses/index.jsonl", "capture_level": "adapter DataFrame before normalization; original Yahoo HTTP bytes unavailable",
            "archive_status": "Raw response archive only; not a validated immutable research dataset"}


def _daily_report(output, config, result, mode, source, provenance, errors):
    day_config = config.model_copy(update={"initial_cash": result["initial_equity"]})
    provenance = [{**item, "raw_capture_ref": f"../{item['raw_capture_ref']}"} if "raw_capture_ref" in item else item for item in provenance]
    return write_report(Path(output) / result["session"], day_config, [result], mode=mode, source=source,
                        provenance=provenance, errors=errors)


def _progress(output, agent, source, *, state="observing"):
    """Cheap atomic snapshots; chart rendering stays outside the bar loop."""
    result = agent.result()
    snapshot = {"updated_at": _utcnow().isoformat(), "state": state, "source": source,
                "session": result["session"], "session_open": result["session_open"], "session_close": result["session_close"],
                "valuation_timestamp": result["valuation_timestamp"], "cash": agent.portfolio.cash,
                "finished": agent.finished, "completed_bars": len(agent.history[agent.config.symbols[0]]),
                "holdings": result["holdings"], "equity": result["equity"], "fills": result["fills"][-20:],
                "decisions": result["decisions"][-10:], "halt_reason": result["halt_reason"]}
    Path(output).mkdir(parents=True, exist_ok=True)
    atomic_text(Path(output) / "progress.json", json.dumps(snapshot, allow_nan=False))


def run_backtest(config, start, end, output, *, feed=None, calendar=None, policy_factory=None, now=None):
    calendar = calendar or MarketCalendar()
    archive_source = feed is None
    feed = feed if feed is not None else _archived_yahoo_feed(output)
    sessions = calendar.sessions(start, end)
    if not sessions:
        raise ValueError("No NYSE sessions in this date range")
    clock = pd.Timestamp(now or _utcnow()).tz_convert("UTC")
    if sessions[-1].close > clock:
        raise ValueError("Historical replay requires completed sessions; use watch for an ongoing session")
    results, provenance, errors = [], [_archive_provenance()] if archive_source else [], []
    source = "Yahoo Finance via yfinance (request not completed)"
    cash = config.initial_cash
    try:
        data = feed.fetch(config.symbols, start, end, config.interval)
        source = data.source; provenance.append(_provenance(data))
        for session in sessions:
            agent = IntradayAgent(config, session, cash, policy_factory() if policy_factory else None)
            try:
                frames = session_frames(data, session, config)
                for timestamp in session.grid(config.minutes):
                    agent.observe(timestamp, {symbol: frame.loc[timestamp].to_dict() for symbol, frame in frames.items()})
                    _progress(output, agent, source)
                result = agent.result()
            except KeyboardInterrupt:
                errors.append(f"{session.date}: replay interrupted; open positions remain marked at their last observed prices")
                result = agent.result()
                result["status"] = "interrupted"
            except Exception as error:
                errors.append(f"{session.date}: {error}")
                result = agent.result()
                result["status"] = "data_or_execution_error"
            _progress(output, agent, source, state=result["status"])
            results.append(result)
            _daily_report(output, config, result, "historical_replay", source, provenance, errors)
            if not result["finished"]:
                break
            cash = agent.portfolio.cash
            if cash <= 0:
                errors.append("Capital exhausted; later sessions were not simulated")
                break
    except KeyboardInterrupt:
        errors.append("Run interrupted; results include only processed observations")
    except Exception as error:
        errors.append(str(error))
    record = write_report(output, config, results, mode="historical_replay", source=source, provenance=provenance, errors=errors)
    return record


def run_watch(config, output, *, session_count=1, feed=None, calendar=None, policy_factory=None, clock=_utcnow, sleep=time.sleep):
    if session_count is not None and session_count < 1:
        raise ValueError("session_count must be positive")
    archive_source = feed is None
    calendar, feed = calendar or MarketCalendar(), feed if feed is not None else _archived_yahoo_feed(output)
    results, provenance, errors = [], [_archive_provenance()] if archive_source else [], []
    source = "Yahoo Finance via yfinance (awaiting source data)"
    cash = config.initial_cash
    interrupted = False
    for _ in count() if session_count is None else range(session_count):
        session = calendar.upcoming(clock())
        agent = IntradayAgent(config, session, cash, policy_factory() if policy_factory else None)
        failures = 0
        _progress(output, agent, source, state="waiting_for_data")
        try:
            while not agent.finished:
                now = pd.Timestamp(clock()).tz_convert("UTC")
                deadline = session.close + pd.Timedelta(seconds=config.data_lag_seconds + config.close_grace_seconds)
                if now > deadline:
                    errors.append(f"{session.date}: close deadline passed before a complete session was available")
                    break
                complete_until = min(now - pd.Timedelta(seconds=config.data_lag_seconds), session.close)
                first_end = session.bar_end(session.open, config.minutes)
                if complete_until < first_end:
                    sleep(min(config.poll_seconds, max(1, (first_end - complete_until).total_seconds())))
                    continue
                try:
                    data = feed.fetch(config.symbols, session.date, session.date, config.interval)
                    source = data.source; provenance.append(_provenance(data))
                    frames = session_frames(data, session, config, complete_until=complete_until)
                    for timestamp in next(iter(frames.values())).index:
                        if agent.observe(timestamp, {symbol: frame.loc[timestamp].to_dict() for symbol, frame in frames.items()}):
                            _progress(output, agent, source)
                    failures = 0
                except DataError as error:
                    failures += 1
                    provenance.append({"timestamp": now.isoformat(), "error": str(error), "consecutive_failures": failures})
                    _progress(output, agent, source, state=f"data_error: {error}")
                    if failures >= config.max_data_errors:
                        errors.append(f"{session.date}: data failure limit reached: {error}")
                        break
                if not agent.finished:
                    sleep(config.poll_seconds)
        except KeyboardInterrupt:
            errors.append("Polling interrupted; open positions remain marked at their last observed prices")
            interrupted = True
        except Exception as error:
            errors.append(f"{session.date}: {error}")
        result = agent.result()
        _progress(output, agent, source, state=result["status"])
        results.append(result)
        _daily_report(output, config, result, "near_real_time_delayed_replay", source, provenance, errors)
        write_report(output, config, results, mode="near_real_time_delayed_replay", source=source, provenance=provenance, errors=errors)
        if interrupted or not agent.finished or agent.portfolio.cash <= 0 or result["halt_reason"] == "decision_error_limit":
            break
        cash = agent.portfolio.cash
        _progress(output, agent, source, state="waiting_for_next_session")
        # Advance to the next session, rather than re-entering the current one if
        # the source supplied its closing bar before this polling clock advanced.
        while pd.Timestamp(clock()).tz_convert("UTC") <= session.close:
            sleep(min(config.poll_seconds, max(1, (session.close - pd.Timestamp(clock())).total_seconds() + 1)))
    return write_report(output, config, results, mode="near_real_time_delayed_replay", source=source, provenance=provenance, errors=errors)
