"""Content-addressed adapter responses and immutable, inspected OHLCV datasets."""
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import tempfile
from uuid import uuid4

import numpy as np
import pandas as pd

from .calendar import MarketCalendar
from .config import AgentConfig
from .data import DataError, MarketData, SyntheticFeed, YahooFinanceFeed, clean_bars
from .reporting import atomic_text


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def _safe(value):
    if isinstance(value, dict):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [_safe(item) for item in value]
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return _safe(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is pd.NA or value is pd.NaT:
        return None
    return value


def canonical(value):
    return json.dumps(_safe(value), sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)


def checksum(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def frame_record(frame):
    """Preserve all adapter columns, row order, values and dtype descriptions."""
    def raw_value(value):
        if isinstance(value, np.generic):
            value = value.item()
        if isinstance(value, float) and not math.isfinite(value):
            return {"nonfinite": repr(value)}
        if value is pd.NA or value is pd.NaT:
            return {"missing_type": str(value)}
        return _safe(value)
    return {"columns": list(frame.columns), "index": [stamp.isoformat() for stamp in frame.index],
            "index_dtype": str(frame.index.dtype), "index_name": frame.index.name,
            "data": [[raw_value(value) for value in row] for row in frame.itertuples(index=False, name=None)],
            "dtypes": {str(key): str(value) for key, value in frame.dtypes.items()}}


def record_frame(record):
    return pd.DataFrame(record["data"], index=pd.to_datetime(record["index"], utc=True), columns=record["columns"]).astype(float)


class DatasetStore:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _directory(self, dataset_id):
        if not re.fullmatch(r"[a-f0-9]{64}", dataset_id):
            raise ValueError("Use an exact SHA-256 dataset_id")
        directory = self.root / dataset_id
        if not directory.is_dir():
            raise KeyError("Unknown immutable dataset")
        return directory

    def inspect(self, dataset_id):
        directory = self._directory(dataset_id)
        manifest = json.loads((directory / "manifest.json").read_text())
        expected_id = hashlib.sha256(canonical({key: value for key, value in manifest.items() if key != "dataset_id"}).encode()).hexdigest()
        if expected_id != dataset_id or manifest.get("dataset_id") != dataset_id:
            raise DataError("Dataset manifest checksum mismatch")
        for name, digest in manifest["files"].items():
            if Path(name).name != name or checksum(directory / name) != digest:
                raise DataError(f"Dataset checksum mismatch: {name}")
        return manifest

    def list(self, limit=20):
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 50:
            raise ValueError("Dataset listing limit must be 1–50")
        directories = sorted((item for item in self.root.iterdir() if re.fullmatch(r"[a-f0-9]{64}", item.name)),
                             key=lambda item: item.stat().st_mtime, reverse=True)
        return [self.inspect(item.name) for item in directories[:limit]]

    def load(self, dataset_id):
        manifest = self.inspect(dataset_id)
        if not manifest["quality"]["usable"]:
            raise DataError("Dataset quality failed: " + "; ".join(manifest["quality"]["errors"]))
        directory = self._directory(dataset_id)
        frames = {symbol: record_frame(json.loads((directory / f"bars-{number}.json").read_text()))
                  for number, symbol in enumerate(manifest["request"]["symbols"])}
        return MarketData(frames, manifest["source"], manifest["retrieved_at"], manifest["instruments"]), manifest

    def save(self, data, request, *, raw_responses=None, calendar=None):
        """Save even rejected quality reports; no in-place correction or resampling."""
        calendar = calendar or MarketCalendar()
        sessions = calendar.sessions(request["start"], request["end"])
        config = AgentConfig(symbols=request["symbols"], interval=request["interval"])
        expected = pd.DatetimeIndex([stamp for session in sessions for stamp in session.grid(config.minutes)])
        errors, warnings, instruments = [], [], {}
        if not sessions:
            errors.append("No XNYS sessions in the requested date range")
        if sessions and sessions[-1].close > pd.Timestamp.now(tz="UTC"):
            errors.append("Dataset includes an incomplete or future session")
        responses = raw_responses or [{"symbol": symbol, "frame": frame_record(frame), "metadata": data.metadata.get(symbol, {}),
                                      "request": request, "retrieved_at": data.retrieved_at, "adapter_level": True}
                                     for symbol, frame in data.frames.items()]
        actions = []
        for response in responses:
            raw = response.get("frame")
            if not raw:
                if response.get("error"):
                    errors.append(f"{response['symbol']}: {response['error']}")
                continue
            for column in ["Stock Splits", "Dividends", "Capital Gains"]:
                if column in raw["columns"]:
                    offset = raw["columns"].index(column)
                    for stamp, row in zip(raw["index"], raw["data"]):
                        if isinstance(row[offset], (int, float)) and row[offset] != 0:
                            actions.append({"symbol": response["symbol"], "timestamp": stamp, "type": column, "value": row[offset]})
        if actions:
            errors.append("Corporate actions present; split/dividend accounting is unsupported for research datasets")
        for symbol in request["symbols"]:
            frame = data.frames.get(symbol)
            if frame is None:
                errors.append(f"{symbol}: unavailable observations")
                continue
            duplicate_count = int(frame.index.duplicated().sum())
            missing = expected.difference(frame.index)
            extra = frame.index.difference(expected)
            invalid = None
            try:
                clean_bars(frame)
            except DataError as error:
                invalid = str(error)
                errors.append(f"{symbol}: {error}")
            if len(missing):
                errors.append(f"{symbol}: {len(missing)} missing requested bars; no observations filled")
            if len(extra):
                errors.append(f"{symbol}: {len(extra)} unexpected bars; requested dataset was not trimmed")
            currency = data.metadata.get(symbol, {}).get("currency")
            if currency != "USD":
                errors.append(f"{symbol}: unsupported or unavailable currency {currency}")
            exchange = data.metadata.get(symbol, {}).get("exchange")
            if not data.source.startswith("SYNTHETIC") and exchange not in {"NYQ", "NMS", "NGM", "NCM", "ASE", "PCX", "BTS", "BATS", "NYSE", "NASDAQ", "NasdaqGS", "NasdaqGM", "NasdaqCM"}:
                errors.append(f"{symbol}: exchange {exchange!r} has not been verified compatible with the XNYS session adapter")
            instruments[symbol] = {"rows": len(frame), "expected_rows": len(expected), "duplicate_count": duplicate_count,
                                   "missing_count": len(missing), "first_missing": missing[0].isoformat() if len(missing) else None,
                                   "unexpected_count": len(extra), "invalid": invalid,
                                   "first_timestamp": frame.index.min().isoformat() if len(frame) else None,
                                   "last_timestamp": frame.index.max().isoformat() if len(frame) else None}
        warnings.extend(["Aggregated OHLCV bars; no trades, quotes, spreads, depth or executable volume model",
                         "No point-in-time universe/delisting completeness guarantee; selection and survivorship bias possible"])
        quality = {"usable": not errors, "errors": errors, "warnings": warnings, "instruments": instruments,
                   "corporate_actions": actions[:100], "corporate_action_count": len(actions)}
        with tempfile.TemporaryDirectory(prefix=".dataset-", dir=self.root) as temporary:
            directory = Path(temporary)
            for number, symbol in enumerate(request["symbols"]):
                if symbol in data.frames:
                    (directory / f"bars-{number}.json").write_text(canonical(frame_record(data.frames[symbol])))
            (directory / "raw.json").write_text(canonical(responses))
            (directory / "quality.json").write_text(canonical(quality))
            observation_fingerprint = hashlib.sha256(canonical({"symbols": request["symbols"], "interval": request["interval"],
                "bars": {path.name: checksum(path) for path in sorted(directory.glob("bars-*.json"))}}).encode()).hexdigest()
            manifest = {"schema_version": "1.0.0", "request": request, "source": data.source, "retrieved_at": data.retrieved_at,
                        "observation_fingerprint": observation_fingerprint,
                        "created_at": utcnow(), "observation_type": "aggregated_ohlcv", "timezone": "UTC", "calendar": "XNYS",
                        "adjustments": {"auto_adjust": False, "repair": False, "prepost": False, "actions": True},
                        "raw_capture_level": "adapter DataFrame before normalization; original Yahoo HTTP bytes unavailable",
                        "instruments": data.metadata, "sessions": [session.date for session in sessions], "quality": quality,
                        "files": {path.name: checksum(path) for path in sorted(directory.iterdir())}}
            dataset_id = hashlib.sha256(canonical(manifest).encode()).hexdigest()
            manifest["dataset_id"] = dataset_id
            (directory / "manifest.json").write_text(canonical(manifest))
            destination = self.root / dataset_id
            if destination.exists():
                self.inspect(dataset_id)
            else:
                directory.rename(destination)
                for path in destination.iterdir():
                    path.chmod(0o444)
                destination.chmod(0o555)
        return manifest

    def acquire(self, request, *, feed=None, calendar=None):
        calendar = calendar or MarketCalendar()
        acquisition = self.root / "acquisitions" / uuid4().hex
        acquisition.mkdir(parents=True)
        responses = []

        def capture(symbol, parameters, frame, metadata, error):
            response = {"symbol": symbol, "request": parameters, "retrieved_at": utcnow(), "metadata": metadata,
                        "frame": frame_record(frame) if frame is not None else None, "error": error, "adapter_level": True}
            responses.append(response)
            path = acquisition / f"response-{len(responses):04}.json"
            with path.open("x") as stream:
                stream.write(canonical(response))
            path.chmod(0o444)

        atomic_text(acquisition / "request.json", canonical(request))
        try:
            selected = feed or (SyntheticFeed(calendar.sessions(request["start"], request["end"]), request.get("seed", 7))
                                if request["source"] == "synthetic" else YahooFinanceFeed(response_sink=capture))
            data = selected.fetch(request["symbols"], request["start"], request["end"], request["interval"])
            manifest = self.save(data, request, raw_responses=responses, calendar=calendar)
            atomic_text(acquisition / "result.json", canonical({"dataset_id": manifest["dataset_id"], "usable": manifest["quality"]["usable"]}))
            return manifest
        except BaseException as error:
            atomic_text(acquisition / "failure.json", canonical({"error": str(error) or type(error).__name__, "timestamp": utcnow(),
                                                                "responses": [{"file": path.name, "sha256": checksum(path)} for path in acquisition.glob("response-*.json")]}))
            raise
