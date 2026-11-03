"""Bounded read-only IQ snapshot transport. Never send tasks or credentials."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

URL = "https://codexradar.com/data/codex-four-task-summary.json"
PROTOCOL = "codex-four-weighted-150-v2"
MAX_BYTES = 256 * 1024
ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}\Z")
HASH = re.compile(r"[a-f0-9]{64}\Z")


class SnapshotError(ValueError):
    pass


def utc(value):
    if not isinstance(value, str):
        raise SnapshotError("missing_time")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SnapshotError("invalid_time") from exc
    if result.tzinfo is None:
        raise SnapshotError("naive_time")
    return result.astimezone(timezone.utc)


def number(value, minimum=0, maximum=1e12):
    return (type(value) in (int, float) and math.isfinite(value)
            and minimum <= value <= maximum)


def parse(raw, *, now=None, max_age_hours=72):
    """Validate each batch independently; fetch time cannot freshen old scores."""
    now = now or datetime.now(timezone.utc)
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
        raise SnapshotError("response_size")
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise SnapshotError("invalid_json") from exc
    if not isinstance(data, dict) or data.get("protocol") != PROTOCOL:
        raise SnapshotError("unsupported_protocol")
    batch = data.get("round_id")
    if not isinstance(batch, str) or not ID.fullmatch(batch):
        raise SnapshotError("invalid_batch")
    interval = data.get("author_test_interval")
    if not isinstance(interval, dict):
        raise SnapshotError("missing_interval")
    start, end = utc(interval.get("started_at")), utc(interval.get("completed_at"))
    age = (now - end).total_seconds()
    if start > end or age < -300:
        raise SnapshotError("invalid_interval")
    if age > max_age_hours * 3600:
        raise SnapshotError("stale_batch")
    rows = data.get("rows")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 512:
        raise SnapshotError("invalid_rows")
    clean, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            raise SnapshotError("invalid_row")
        model, effort = row.get("model"), row.get("effort")
        if (not isinstance(model, str) or not ID.fullmatch(model)
                or effort not in ("none", "low", "medium", "high", "xhigh", "max", "ultra")):
            raise SnapshotError("invalid_identity")
        if (model, effort) in seen:
            raise SnapshotError("duplicate_identity")
        seen.add((model, effort))
        score, cost, seconds = (row.get(k) for k in
                                ("score150", "cost_usd", "model_elapsed_seconds"))
        if not number(score, 0, 150):
            raise SnapshotError("invalid_score")
        if cost is not None and not number(cost, 0, 1e6):
            raise SnapshotError("invalid_cost")
        if seconds is not None and not number(seconds, 0, 86400 * 30):
            raise SnapshotError("invalid_duration")
        # Missing or differently defined prices stay unknown, never become zero.
        if row.get("cost_kind") != "api_equivalent_estimate":
            cost = None
        clean.append(dict(model=model, effort=effort, score150=score,
                          cost_usd=cost, model_elapsed_seconds=seconds))
    hashes = {}
    for key in ("source_sha256", "review_sha256", "pricing_projection_sha256"):
        value = data.get(key)
        if not isinstance(value, str) or not HASH.fullmatch(value):
            raise SnapshotError("missing_provenance_hash")
        hashes[key] = value
    return dict(protocol=PROTOCOL, round_id=batch, source_url=URL,
                measured_from=start.isoformat(), measured_until=end.isoformat(),
                sha256=hashlib.sha256(raw).hexdigest(), hashes=hashes, rows=clean,
                cost_basis="api_equivalent_estimate_not_subscription_billing")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch(timeout_ms):
    req = urllib.request.Request(URL, headers={
        "Accept": "application/json", "Accept-Encoding": "identity",
        "User-Agent": "AgentRouter-IQ/1.0 (read-only, user-opt-in)",
    })
    # No task query, cookies, API key, remote code execution or retry.
    with urllib.request.build_opener(NoRedirect).open(req, timeout=timeout_ms / 1000) as response:
        if response.status != 200 or response.headers.get_content_type() != "application/json":
            raise SnapshotError("unexpected_http_response")
        raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise SnapshotError("response_size")
        return raw


def isolated_fetch(timeout_ms):
    """OS subprocess, not a model Worker; bounds DNS/read stalls as well."""
    try:
        result = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("radar_worker.py")), str(timeout_ms)],
            capture_output=True, timeout=timeout_ms / 1000, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise SnapshotError("fetch_deadline") from exc
    if result.returncode != 0 or len(result.stdout) > MAX_BYTES:
        raise SnapshotError("fetch_failed")
    return result.stdout


def _read(path, limit):
    if path.is_symlink():
        raise SnapshotError("cache_symlink")
    with path.open("rb") as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise SnapshotError("cache_size")
    return data


def _write(path, value):
    if path.is_symlink():
        raise SnapshotError("cache_symlink")
    fd, name = tempfile.mkstemp(prefix=".radar-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def load(directory, config, *, now=None, fetcher=None):
    """One attempt per refresh interval across processes; no network while waiting."""
    now = now or datetime.now(timezone.utc)
    directory = Path(directory)
    if directory.is_symlink():
        raise SnapshotError("cache_symlink")
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    path, attempt, lock = (directory / n for n in ("iq-cache.json", "last-attempt.json", "fetch.lock"))
    cached = None
    try:
        stored = json.loads(_read(path, 2 * MAX_BYTES))
        if stored.get("source_url") != URL:
            raise SnapshotError("cache_source")
        raw = stored["raw"].encode("utf-8")
        age = (now - utc(stored["retrieved_at"])).total_seconds()
        if age < -300:
            raise SnapshotError("future_cache")
        cached = parse(raw, now=now, max_age_hours=config["max_age_hours"])
        cached["retrieved_at"] = stored["retrieved_at"]
        if age <= config["refresh_seconds"]:
            return cached, "cache", False
    except (ValueError, OSError, KeyError, TypeError, AttributeError):
        pass
    def fallback(reason):
        if cached is not None:
            return cached, "cached_after_" + reason, False
        raise SnapshotError(reason)
    cooling = False
    try:
        recent = json.loads(_read(attempt, 2048))
        elapsed = (now - utc(recent["at"])).total_seconds()
        cooling = -300 <= elapsed < config["refresh_seconds"]
    except (OSError, KeyError, TypeError, ValueError):
        pass
    if cooling:
        return fallback("refresh_cooldown")
    try:
        lock.mkdir()
    except FileExistsError:
        # An orphan lock is ignored after a short, bounded lease.
        try:
            if lock.is_symlink() or time.time() - lock.stat().st_mtime < 60:
                return fallback("refresh_in_progress")
            lock.rmdir()
            lock.mkdir()
        except OSError:
            return fallback("refresh_in_progress")
    try:
        # Check again under the lease so concurrent planners cannot stampede.
        cooling = False
        try:
            recent = json.loads(_read(attempt, 2048))
            elapsed = (now - utc(recent["at"])).total_seconds()
            cooling = -300 <= elapsed < config["refresh_seconds"]
        except (OSError, KeyError, TypeError, ValueError):
            pass
        if cooling:
            return fallback("refresh_cooldown")
        _write(attempt, dict(at=now.isoformat()))
        try:
            raw = (fetcher or isolated_fetch)(config["fetch_timeout_ms"])
            candidate = parse(raw, now=now, max_age_hours=config["max_age_hours"])
            if cached is not None and utc(candidate["measured_until"]) < utc(cached["measured_until"]):
                raise SnapshotError("older_batch_replay")
            _write(path, dict(source_url=URL, retrieved_at=now.isoformat(), raw=raw.decode("utf-8")))
            candidate["retrieved_at"] = now.isoformat()
            return candidate, "network", True
        except (OSError, ValueError, UnicodeError):
            if cached is not None:
                return cached, "cached_after_refresh_failure", True
            raise SnapshotError("no_valid_snapshot")
    finally:
        try:
            lock.rmdir()
        except OSError:
            pass
